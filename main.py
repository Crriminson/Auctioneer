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
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                # Remove broken connections
                self.active_connections.remove(connection)

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

def create_tables():
    """Create necessary tables in Supabase"""
    try:
        # Create auctions table
        supabase.table('auctions').select('*').limit(1).execute()
    except:
        # Table doesn't exist, let's create it via SQL
        print("Tables need to be created in Supabase dashboard")
        print("""
        Run these SQL commands in Supabase SQL Editor:
        
        -- Create auctions table
        CREATE TABLE IF NOT EXISTS auctions (
            id BIGSERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            current_bid DECIMAL(10,2) DEFAULT 0,
            minimum_bid DECIMAL(10,2) NOT NULL,
            end_time TIMESTAMP WITH TIME ZONE NOT NULL,
            status TEXT DEFAULT 'active' CHECK (status IN ('active', 'ended', 'cancelled')),
            bid_count INTEGER DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );

        -- Create bids table
        CREATE TABLE IF NOT EXISTS bids (
            id BIGSERIAL PRIMARY KEY,
            auction_id BIGINT REFERENCES auctions(id) ON DELETE CASCADE,
            user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
            user_email TEXT NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );

        -- Create indexes for better performance
        CREATE INDEX IF NOT EXISTS idx_auctions_status ON auctions(status);
        CREATE INDEX IF NOT EXISTS idx_auctions_end_time ON auctions(end_time);
        CREATE INDEX IF NOT EXISTS idx_bids_auction_id ON bids(auction_id);
        CREATE INDEX IF NOT EXISTS idx_bids_user_id ON bids(user_id);

        -- Enable Row Level Security
        ALTER TABLE auctions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE bids ENABLE ROW LEVEL SECURITY;

        -- Create policies for auctions (everyone can read, authenticated users can create)
        CREATE POLICY "Anyone can view auctions" ON auctions FOR SELECT USING (true);
        CREATE POLICY "Authenticated users can create auctions" ON auctions FOR INSERT WITH CHECK (auth.role() = 'authenticated');
        CREATE POLICY "Authenticated users can update auctions" ON auctions FOR UPDATE USING (auth.role() = 'authenticated');

        -- Create policies for bids (everyone can read, authenticated users can create their own)
        CREATE POLICY "Anyone can view bids" ON bids FOR SELECT USING (true);
        CREATE POLICY "Authenticated users can create bids" ON bids FOR INSERT WITH CHECK (auth.uid() = user_id);
        """)

# API Routes

@app.on_event("startup")
async def startup_event():
    """Initialize the application"""
    create_tables()
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
        auction_data = {
            "title": auction.title,
            "description": auction.description,
            "minimum_bid": auction.minimum_bid,
            "current_bid": auction.minimum_bid,
            "end_time": auction.end_time.isoformat(),
            "status": "active",
            "bid_count": 0
        }
        
        response = supabase.table('auctions').insert(auction_data).execute()
        
        if response.data:
            # Broadcast new auction to all connected clients
            await manager.broadcast(json.dumps({
                "type": "new_auction",
                "data": response.data[0]
            }))
            return response.data[0]
        else:
            raise HTTPException(status_code=400, detail="Failed to create auction")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create auction: {str(e)}")

@app.put("/auctions/{auction_id}", response_model=AuctionResponse)
async def update_auction(auction_id: int, auction: AuctionUpdate, current_user = Depends(get_current_user)):
    """Update an existing auction"""
    try:
        update_data = {k: v for k, v in auction.dict().items() if v is not None}
        
        if update_data:
            update_data["updated_at"] = datetime.now().isoformat()
            
            response = supabase.table('auctions').update(update_data).eq('id', auction_id).execute()
            
            if response.data:
                # Broadcast auction update
                await manager.broadcast(json.dumps({
                    "type": "auction_updated",
                    "data": response.data[0]
                }))
                return response.data[0]
            else:
                raise HTTPException(status_code=404, detail="Auction not found")
        else:
            raise HTTPException(status_code=400, detail="No data provided for update")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update auction: {str(e)}")

# Bidding routes
@app.post("/bids")
async def place_bid(bid: BidCreate, current_user = Depends(get_current_user)):
    """Place a bid on an auction"""
    try:
        # First, get the current auction details
        auction_response = supabase.table('auctions').select('*').eq('id', bid.auction_id).execute()
        
        if not auction_response.data:
            raise HTTPException(status_code=404, detail="Auction not found")
        
        auction = auction_response.data[0]
        
        # Check if auction is still active
        if auction['status'] != 'active':
            raise HTTPException(status_code=400, detail="Auction is not active")
        
        # Check if auction has ended
        if datetime.fromisoformat(auction['end_time'].replace('Z', '+00:00')) <= datetime.now():
            raise HTTPException(status_code=400, detail="Auction has ended")
        
        # Check if bid is higher than current bid
        if bid.amount <= auction['current_bid']:
            raise HTTPException(
                status_code=400, 
                detail=f"Bid must be higher than current bid of ${auction['current_bid']}"
            )
        
        # Create the bid record
        bid_data = {
            "auction_id": bid.auction_id,
            "user_id": current_user.id,
            "user_email": current_user.email,
            "amount": bid.amount
        }
        
        bid_response = supabase.table('bids').insert(bid_data).execute()
        
        if not bid_response.data:
            raise HTTPException(status_code=400, detail="Failed to place bid")
        
        # Update the auction with new current bid and increment bid count
        update_response = supabase.table('auctions').update({
            "current_bid": bid.amount,
            "bid_count": auction['bid_count'] + 1,
            "updated_at": datetime.now().isoformat()
        }).eq('id', bid.auction_id).execute()
        
        if update_response.data:
            # Broadcast the new bid to all connected clients
            await manager.broadcast(json.dumps({
                "type": "new_bid",
                "data": {
                    "auction_id": bid.auction_id,
                    "bid": bid_response.data[0],
                    "auction": update_response.data[0]
                }
            }))
            
            return {
                "message": "Bid placed successfully",
                "bid": bid_response.data[0],
                "auction": update_response.data[0]
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update auction")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to place bid: {str(e)}")

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
        # Total auctions
        total_auctions = supabase.table('auctions').select('id', count='exact').execute()
        
        # Active auctions
        active_auctions = supabase.table('auctions').select('id', count='exact').eq('status', 'active').execute()
        
        # Total bids
        total_bids = supabase.table('bids').select('id', count='exact').execute()
        
        # Top auctions by bid count
        top_auctions = supabase.table('auctions').select('title', 'bid_count', 'current_bid').order('bid_count', desc=True).limit(10).execute()
        
        return {
            "total_auctions": total_auctions.count,
            "active_auctions": active_auctions.count,
            "total_bids": total_bids.count,
            "top_auctions": top_auctions.data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch analytics: {str(e)}")

# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time auction updates"""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            # Echo back any received messages (for testing)
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Background task to end expired auctions
async def end_expired_auctions():
    """Background task to automatically end expired auctions"""
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
                    await manager.broadcast(json.dumps({
                        "type": "auction_ended",
                        "data": auction
                    }))
            
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