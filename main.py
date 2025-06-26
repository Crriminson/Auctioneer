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
import requests

# Load environment variables
load_dotenv()

# Supabase configuration
SUPABASE_URL = "https://hcymzipntbienmdmmjqm.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhjeW16aXBudGJpZW5tZG1tanFtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTA2MjI0MjcsImV4cCI6MjA2NjE5ODQyN30.iCH95PpaeF8aO1MNAB9tr72JBZRdDNrzuiASCcFw9ME"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Omnidimension API configuration
OMNIDIMENSION_API_KEY = "ec21a1cec126397ada88647c4efe2a79"
OMNIDIMENSION_API_URL = "https://backend.omnidim.io/api/v1"

# FastAPI app
app = FastAPI(title="Auctioneer API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],  # Only allow your frontend origin
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

# Omnidimension API helper functions
async def send_voice_notification(message: str, room_id: str = None):
    """Send a voice notification using Omnidimension"""
    try:
        response = requests.post(
            f"{OMNIDIMENSION_API_URL}/speak",
            headers={"Authorization": f"Bearer {OMNIDIMENSION_API_KEY}"},
            json={"text": message, "room_id": room_id}
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error sending voice notification: {e}")
        return None

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
        # Auto-confirm user for instant login (dev only)
        if response.user:
            # Patch user to confirmed (bypass email verification)
            supabase.auth.admin.update_user_by_id(response.user.id, {"email_confirmed": True})
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

@app.get("/auth/session")
async def get_session(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Return current user session info if authenticated, else 401."""
    try:
        user = await get_current_user(credentials)
        return {"user": {"id": user.id, "email": user.email}}
    except Exception:
        return {"user": None}

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
        # Add default values for new auctions
        auction_data = {
            **auction.dict(),
            'status': 'active',
            'current_bid': auction.minimum_bid,
            'bid_count': 0,
            'created_at': datetime.now().isoformat()
        }
        
        response = supabase.table('auctions').insert(auction_data).select().execute()
        
        if response.data:
            created_auction = response.data[0]
            print(f"New auction created: {created_auction['id']}")
            # Start the cleanup task for this auction
            asyncio.create_task(schedule_auction_end(created_auction['id'], auction.end_time))
            return created_auction
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

# Background task to check for expired auctions
async def end_expired_auctions():
    """Background task to check and end expired auctions"""
    while True:
        try:
            current_time = datetime.now()
            print(f"[Auction Cleanup] Checking for expired auctions at {current_time.isoformat()}")
            
            # Find expired auctions that are still active
            expired_auctions = supabase.table('auctions')\
                .select('*')\
                .lt('end_time', current_time.isoformat())\
                .eq('status', 'active')\
                .execute()
            
            if expired_auctions.data:
                print(f"[Auction Cleanup] Found {len(expired_auctions.data)} expired auctions")
                for auction in expired_auctions.data:
                    try:
                        auction_id = auction['id']
                        print(f"[Auction Cleanup] Processing auction ID {auction_id}...")
                        
                        # 1. Find the winner (highest bidder)
                        winner_bid = supabase.table('bids')\
                            .select('*')\
                            .eq('auction_id', auction_id)\
                            .order('amount', desc=True)\
                            .limit(1)\
                            .execute()
                        
                        if winner_bid.data:
                            # 2. Store winner information
                            winner = winner_bid.data[0]
                            winner_entry = {
                                'auction_id': auction_id,
                                'auction_title': auction['title'],
                                'user_id': winner['user_id'],
                                'user_email': winner['user_email'],
                                'amount': winner['amount'],
                                'created_at': datetime.now().isoformat()
                            }
                            
                            supabase.table('winners').insert(winner_entry).execute()
                            
                            # Send notification about the winner
                            winner_message = f"Auction for {auction['title']} has ended. Winner is {winner['user_email']} with bid of ₹{winner['amount']}"
                            await send_voice_notification(winner_message)
                            print(f"[Auction Cleanup] {winner_message}")
                        
                        # 3. Mark auction as ended
                        supabase.table('auctions')\
                            .update({'status': 'ended'})\
                            .eq('id', auction_id)\
                            .execute()
                        
                        # 4. Delete all bids for this auction
                        try:
                            bids_delete_resp = supabase.table('bids')\
                                .delete()\
                                .eq('auction_id', auction_id)\
                                .execute()
                            print(f"[Auction Cleanup] Bids delete response for auction {auction_id}: {bids_delete_resp}")
                        except Exception as del_bids_exc:
                            print(f"[Auction Cleanup] Error deleting bids for auction {auction_id}: {del_bids_exc}")

                        # 5. Delete the auction
                        try:
                            auction_delete_resp = supabase.table('auctions')\
                                .delete()\
                                .eq('id', auction_id)\
                                .execute()
                            print(f"[Auction Cleanup] Auction delete response for auction {auction_id}: {auction_delete_resp}")
                        except Exception as del_auction_exc:
                            print(f"[Auction Cleanup] Error deleting auction {auction_id}: {del_auction_exc}")
                        
                        print(f"[Auction Cleanup] Successfully processed and removed auction {auction_id}")
                        
                    except Exception as e:
                        print(f"[Auction Cleanup] Error processing auction {auction_id}: {str(e)}")
                        continue
            
            await asyncio.sleep(30)  # Check every 30 seconds
            
        except Exception as e:
            print(f"Error in auction cleanup: {e}")
            await asyncio.sleep(60)  # Wait longer if there's an error

# Start background task
@app.on_event("startup")
async def startup_background_tasks():
    asyncio.create_task(end_expired_auctions())

# Schedule auction end
async def schedule_auction_end(auction_id: int, end_time: datetime):
    """Schedule the end of an auction"""
    try:
        # Calculate seconds until auction end
        time_until_end = (end_time - datetime.now()).total_seconds()
        if time_until_end > 0:
            print(f"[Auction Scheduler] Scheduling end for auction {auction_id} in {time_until_end} seconds")
            await asyncio.sleep(time_until_end)
            await end_auction(auction_id)
    except Exception as e:
        print(f"Error scheduling auction end: {e}")

# Improved end auction function
async def end_auction(auction_id: int):
    """End an auction immediately"""
    try:
        # Get auction details
        auction_response = supabase.table('auctions')\
            .select('*')\
            .eq('id', auction_id)\
            .eq('status', 'active')\
            .single()\
            .execute()

        if not auction_response.data:
            print(f"[Auction End] Auction {auction_id} not found or already ended")
            return

        auction = auction_response.data
        
        # Get highest bid
        bids = supabase.table('bids')\
            .select('*')\
            .eq('auction_id', auction_id)\
            .order('amount', desc=True)\
            .limit(1)\
            .execute()
        
        if bids.data:
            winner_bid = bids.data[0]
            winner_message = f"Auction for {auction['title']} has ended. Winner is {winner_bid['user_email']} with bid of ₹{winner_bid['amount']}"
            
            # Store winner
            winner_result = supabase.table('winners').insert({
                'auction_id': auction_id,
                'user_id': winner_bid['user_id'],
                'user_email': winner_bid['user_email'],
                'amount': winner_bid['amount'],
                'created_at': datetime.now().isoformat()
            }).execute()
            
            # Send voice notification
            await send_voice_notification(winner_message)
            print(f"[Auction End] {winner_message}")
        
        # Update auction status to ended
        update_result = supabase.table('auctions')\
            .update({'status': 'ended'})\
            .eq('id', auction_id)\
            .execute()
            
        # Broadcast auction end
        try:
            await manager.broadcast_to_auction(
                json.dumps({
                    "type": "auction_ended",
                    "data": {
                        **auction,
                        "status": "ended",
                        "winner": bids.data[0] if bids.data else None
                    }
                }),
                auction_id
            )
        except Exception as e:
            print(f"[Auction End] Failed to broadcast auction end: {e}")
        
        print(f"[Auction End] Successfully ended auction {auction_id}")
        
    except Exception as e:
        print(f"[Auction End] Error ending auction {auction_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Voice command routes
@app.post("/voice/command")
async def handle_voice_command(command: Dict[str, Any]):
    """Handle voice commands from Omnidimension"""
    try:
        transcript = command.get('transcript', '').lower()
        
        # Command: End auction
        if 'end auction' in transcript:
            auction_id = extract_auction_id(transcript)
            if auction_id:
                await end_auction(auction_id)
                return {"message": f"Auction {auction_id} ended successfully"}
        
        # Command: Get auction status
        elif 'auction status' in transcript or 'get status' in transcript:
            auction_id = extract_auction_id(transcript)
            if auction_id:
                status = await get_auction_status(auction_id)
                await send_voice_notification(status)
                return {"message": status}
        
        # Command: List active auctions
        elif 'list auctions' in transcript or 'show auctions' in transcript:
            auctions = await list_active_auctions()
            response = "Current active auctions: " + ", ".join([f"{a['title']} at ₹{a['current_bid']}" for a in auctions])
            await send_voice_notification(response)
            return {"message": response}
        
        return {"message": "Command not recognized"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def extract_auction_id(transcript: str) -> Optional[int]:
    """Extract auction ID from voice command"""
    try:
        words = transcript.split()
        for i, word in enumerate(words):
            if word.isdigit():
                return int(word)
        return None
    except:
        return None

async def end_auction(auction_id: int):
    """End an auction immediately"""
    try:
        auction = supabase.table('auctions').select('*').eq('id', auction_id).single().execute()
        if not auction.data:
            raise HTTPException(status_code=404, detail="Auction not found")
        
        # Process auction ending
        bids = supabase.table('bids').select('*').eq('auction_id', auction_id).order('amount', desc=True).limit(1).execute()
        
        if bids.data:
            winner_bid = bids.data[0]
            await send_voice_notification(f"Ending auction {auction_id}. Winner is {winner_bid['user_email']} with bid of ₹{winner_bid['amount']}")
            
            # Store winner
            supabase.table('winners').insert({
                'auction_id': auction_id,
                'user_id': winner_bid['user_id'],
                'user_email': winner_bid['user_email'],
                'amount': winner_bid['amount'],
                'created_at': datetime.now().isoformat()
            }).execute()
        
        # Delete auction
        supabase.table('auctions').delete().eq('id', auction_id).execute()
        
        # Broadcast to WebSocket
        await manager.broadcast_to_auction(
            json.dumps({
                "type": "auction_ended",
                "data": {**auction.data, "winner": bids.data[0] if bids.data else None}
            }),
            auction_id
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def get_auction_status(auction_id: int) -> str:
    """Get auction status for voice response"""
    try:
        auction = supabase.table('auctions').select('*').eq('id', auction_id).single().execute()
        if not auction.data:
            return f"Auction {auction_id} not found"
        
        end_time = datetime.fromisoformat(auction.data['end_time'].replace('Z', '+00:00'))
        time_left = end_time - datetime.now()
        
        return (
            f"Auction {auction_id} for {auction.data['title']} "
            f"has current bid of ₹{auction.data['current_bid']} "
            f"and {time_left.seconds // 3600} hours {(time_left.seconds // 60) % 60} minutes remaining"
        )
    except Exception as e:
        return f"Error getting auction status: {str(e)}"

async def list_active_auctions() -> List[Dict[str, Any]]:
    """Get list of active auctions"""
    try:
        response = supabase.table('auctions').select('*').eq('status', 'active').execute()
        return response.data or []
    except Exception as e:
        print(f"Error listing active auctions: {e}")
        return []

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)