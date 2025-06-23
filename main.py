from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any
import json
import asyncio
from datetime import datetime, timedelta
import os
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Supabase configuration
SUPABASE_URL = "https://hcymzipntbienmdmmjqm.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhjeW16aXBudGJpZW5tZG1tanFtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTA2MjI0MjcsImV4cCI6MjA2NjE5ODQyN30.iCH95PpaeF8aO1MNAB9tr72JBZRdDNrzuiASCcFw9ME"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# FastAPI app
app = FastAPI(title="Auctioneer API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()

# Pydantic models
class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class AuctionCreate(BaseModel):
    title: str
    description: str
    minimum_bid: float
    end_time: datetime

class AuctionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    minimum_bid: Optional[float] = None
    end_time: Optional[datetime] = None
    current_bid: Optional[float] = None
    status: Optional[str] = None

class BidCreate(BaseModel):
    auction_id: int
    amount: float

class AuctionResponse(BaseModel):
    id: int
    title: str
    description: str
    current_bid: float
    minimum_bid: float
    end_time: datetime
    status: str
    bid_count: int
    created_at: datetime

class BidResponse(BaseModel):
    id: int
    auction_id: int
    user_id: str
    user_email: str
    amount: float
    created_at: datetime

# WebSocket manager for real-time updates
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, auction_id: int):
        await websocket.accept()
        if auction_id not in self.active_connections:
            self.active_connections[auction_id] = []
        self.active_connections[auction_id].append(websocket)

    def disconnect(self, websocket: WebSocket, auction_id: int):
        if auction_id in self.active_connections:
            self.active_connections[auction_id].remove(websocket)
            if not self.active_connections[auction_id]:
                del self.active_connections[auction_id]

    async def broadcast_to_auction(self, message: str, auction_id: int):
        if auction_id in self.active_connections:
            for connection in self.active_connections[auction_id]:
                try:
                    await connection.send_text(message)
                except:
                    # Remove broken connections
                    self.disconnect(connection, auction_id)

manager = ConnectionManager()

# Helper functions
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from JWT token"""
    try:
        # Verify JWT token with Supabase
        response = supabase.auth.get_user(credentials.credentials)
        if response.user:
            return response.user
        else:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token")

# API Routes

@app.on_event("startup")
async def startup_event():
    """Initialize the application"""
    print("Auctioneer API started successfully!")

@app.get("/")
async def root():
    return {"message": "Auctioneer API is running!", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now()}

# Authentication routes
@app.post("/auth/signup")
async def signup(user: UserCreate):
    """User registration"""
    try:
        response = supabase.auth.sign_up({
            "email": user.email,
            "password": user.password
        })
        
        if response.user:
            return {
                "message": "User created successfully",
                "user": {
                    "id": response.user.id,
                    "email": response.user.email
                }
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to create user")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/auth/login")
async def login(user: UserLogin):
    """User login"""
    try:
        response = supabase.auth.sign_in_with_password({
            "email": user.email,
            "password": user.password
        })
        
        if response.session:
            return {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
                "user": {
                    "id": response.user.id,
                    "email": response.user.email
                }
            }
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid credentials")

# Auction routes
@app.get("/auctions", response_model=List[AuctionResponse])
async def get_auctions(status: Optional[str] = None, limit: int = 50):
    """Get all auctions"""
    try:
        query = supabase.table('auctions').select('*')
        
        if status:
            query = query.eq('status', status)
        
        response = query.order('created_at', desc=True).limit(limit).execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch auctions: {str(e)}")

@app.get("/auctions/{auction_id}", response_model=AuctionResponse)
async def get_auction(auction_id: int):
    """Get specific auction by ID"""
    try:
        response = supabase.table('auctions').select('*').eq('id', auction_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="Auction not found")
        
        return response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch auction: {str(e)}")

@app.post("/auctions", response_model=AuctionResponse)
async def create_auction(auction: AuctionCreate, current_user = Depends(get_current_user)):
    """Create a new auction"""
    try:
        response = supabase.table('auctions').insert(auction.dict()).select().execute()
        
        if response.data:
            # Broadcast new auction to the relevant auction room (or a general lobby)
            # For simplicity, we'll just log this for now as there's no "general" room
            print(f"New auction created: {response.data[0]['id']}")
            return response.data[0]
        else:
            raise HTTPException(status_code=400, detail="Failed to create auction")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/auctions/{auction_id}", response_model=AuctionResponse)
async def update_auction(auction_id: int, auction: AuctionUpdate, current_user = Depends(get_current_user)):
    """Update an auction"""
    try:
        response = supabase.table('auctions').update(auction.dict(exclude_unset=True)).eq('id', auction_id).execute()
        
        if response.data:
            # Broadcast update via WebSocket
            await manager.broadcast_to_auction(json.dumps({"type": "auction_update", "data": response.data[0]}), auction_id)
            return response.data[0]
        else:
            raise HTTPException(status_code=404, detail="Auction not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Bidding routes
@app.post("/bids")
async def place_bid(bid: BidCreate, current_user = Depends(get_current_user)):
    """Place a bid on an auction"""
    try:
        # Call the database function to handle the bid atomically
        response = supabase.rpc('place_bid', {
            'auction_id_param': bid.auction_id,
            'bid_amount': bid.amount,
            'user_id_param': str(current_user.id)
        }).execute()

        result = response.data[0]
        if not result['success']:
            raise HTTPException(status_code=400, detail=result['message'])

        # Fetch the updated auction details to broadcast
        auction_response = supabase.table('auctions').select('*').eq('id', bid.auction_id).single().execute()
        
        # Broadcast the new bid to all clients
        await manager.broadcast_to_auction(json.dumps({
            "type": "new_bid",
            "data": {
                "auction_id": bid.auction_id,
                "amount": bid.amount,
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "auction": auction_response.data
            }
        }), bid.auction_id)

        return {"message": result['message']}
    except Exception as e:
        # Catch exceptions from the RPC call or other issues
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

@app.get("/auctions/{auction_id}/bids", response_model=List[BidResponse])
async def get_auction_bids(auction_id: int, limit: int = 50):
    """Get all bids for a specific auction"""
    try:
        response = supabase.table('bids').select('*').eq('auction_id', auction_id).order('created_at', desc=True).limit(limit).execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch bids: {str(e)}")

@app.get("/users/{user_id}/bids", response_model=List[BidResponse])
async def get_user_bids(user_id: str, current_user = Depends(get_current_user)):
    """Get all bids by a specific user"""
    try:
        # Users can only see their own bids unless they're admin
        if current_user.id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        response = supabase.table('bids').select('*').eq('user_id', user_id).order('created_at', desc=True).execute()
        return response.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch user bids: {str(e)}")

# Analytics routes
@app.get("/analytics/auctions")
async def get_auction_analytics():
    """Get auction analytics"""
    try:
        # This is a placeholder for a more complex analytics query
        response = supabase.table('auctions').select('status', 'bid_count').execute()
        
        active_auctions = len([a for a in response.data if a['status'] == 'active'])
        ended_auctions = len([a for a in response.data if a['status'] == 'ended'])
        total_bids = sum([a['bid_count'] for a in response.data])

        return {
            "active_auctions": active_auctions,
            "ended_auctions": ended_auctions,
            "total_bids": total_bids
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# WebSocket endpoint for real-time updates
@app.websocket("/ws/{auction_id}")
async def websocket_endpoint(websocket: WebSocket, auction_id: int):
    await manager.connect(websocket, auction_id)
    try:
        while True:
            # We keep the connection alive, but all broadcasting is done via API endpoints
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, auction_id)

# Background task to end expired auctions
async def end_expired_auctions():
    """Background task to end auctions that have passed their end time"""
    while True:
        try:
            current_time = datetime.now()
            
            # Find expired active auctions
            expired_auctions = supabase.table('auctions').select('*').eq('status', 'active').lt('end_time', current_time.isoformat()).execute()
            
            if expired_auctions.data:
                for auction in expired_auctions.data:
                    # Update auction status to ended
                    supabase.table('auctions').update({
                        "status": "ended",
                        "updated_at": current_time.isoformat()
                    }).eq('id', auction['id']).execute()
                    
                    # Broadcast auction end
                    await manager.broadcast_to_auction(json.dumps({
                        "type": "auction_ended",
                        "data": auction
                    }), auction['id'])
            
            # Sleep for 30 seconds before checking again
            await asyncio.sleep(30)
        except Exception as e:
            print(f"Error in background task: {e}")
            await asyncio.sleep(60)  # Wait longer if there's an error

# Start background task
@app.on_event("startup")
async def startup_background_tasks():
    asyncio.create_task(end_expired_auctions())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)