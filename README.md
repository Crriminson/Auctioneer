# 🎙️ Voice Agent for Real-Time Auction Participation and Bidding

## 🧠 Overview

This project is a **voice-enabled intelligent agent** that allows users to **participate in online auctions via phone calls**. Built using **OmniDimension**, the agent listens, responds, and interacts in real-time with a live or simulated auction system — ensuring users can **stay informed and place timely bids** through voice commands.

---

## 🚀 Problem Statement

Online auctions move quickly — with **bids changing in seconds**, users risk missing out if they can’t act fast. This voice agent bridges that gap by enabling **real-time voice interaction** with the auction platform.

### Key Capabilities:
- Real-time access to auction data
- Informs user about:
  - Available auction items
  - Time remaining
  - Current highest bids
- Accepts **voice-placed bids** (only if higher than the current bid)
- Updates the auction state in real-time

---

## 🎯 Objective

Leverage **OmniDimension** to create a voice agent that:

- Connects with a live/simulated auction system
- Enables voice-based interaction for:
  - Bid placement
  - Auction status queries
- Supports:
  - Bid validation (only allow higher bids)
  - Real-time data updates
- Can report:
  - ✅ Total number of bids per product  
  - ✅ Highest bid for each product  
  - 🏅 (Optional) Full bidding history  

---

## 🛠️ Tech Stack

- **OmniDimension** – Core voice interaction engine
- **Node.js / Python** – Backend API to simulate or integrate auction system
- **WebSockets / REST API** – Real-time data sync
- **Twilio / Phone Gateway** – (Optional) To simulate phone call interaction
- **Database (e.g., MongoDB, PostgreSQL)** – For storing bids and auction history

---

## 🔄 Auction Flow (Voice Agent Logic)

1. **Connects to Auction Backend**
2. **Greets the user and lists active items**
3. **Shares item-specific details upon request**
4. **Accepts a new bid via voice**
5. **Validates if bid is higher than current highest**
6. **Updates auction and confirms bid**
7. **Reports stats on demand**

---

## 📊 Example Responses

- "The highest bid for *Antique Vase* is ₹25,000 by User_21."
- "You have successfully placed a bid of ₹30,000 on *Vintage Clock*."
- "Bidding ends in 2 minutes for *Rare Comic Book*."

---

## 💡 Future Improvements

- Full bidding history logs
- SMS/email confirmation of bids
- User authentication with voice
- Integration with live auction sites (e.g., eBay API)

---

## 📁 Project Structure
- Voice-auction-agent/
 - src/ # Voice agent and business logic
   - agent/ # OmniDimension intents and flows
   - auction/ # Auction simulation or integration
   - utils/ # Helper modules
- data/ # Sample auction items and bids
- README.md
- package.json / requirements.txt
- .env # API keys and configuration


---

## 📞 Get Started

### 1. Clone the Repository
```bash
  git clone https://github.com/your-username/voice-auction-agent.git
  cd voice-auction-agent

# Set Up Environment
