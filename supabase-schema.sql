-- Auctioneer Database Schema for Supabase
-- Run this in the Supabase SQL Editor

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

-- Create user_profiles table for additional user information
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
    email TEXT NOT NULL,
    full_name TEXT,
    avatar_url TEXT,
    total_bids INTEGER DEFAULT 0,
    total_won INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_auctions_status ON auctions(status);
CREATE INDEX IF NOT EXISTS idx_auctions_end_time ON auctions(end_time);
CREATE INDEX IF NOT EXISTS idx_auctions_created_at ON auctions(created_at);
CREATE INDEX IF NOT EXISTS idx_bids_auction_id ON bids(auction_id);
CREATE INDEX IF NOT EXISTS idx_bids_user_id ON bids(user_id);
CREATE INDEX IF NOT EXISTS idx_bids_created_at ON bids(created_at);

-- Enable Row Level Security
ALTER TABLE auctions ENABLE ROW LEVEL SECURITY;
ALTER TABLE bids ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist
DROP POLICY IF EXISTS "Anyone can view auctions" ON auctions;
DROP POLICY IF EXISTS "Authenticated users can create auctions" ON auctions;
DROP POLICY IF EXISTS "Authenticated users can update auctions" ON auctions;
DROP POLICY IF EXISTS "Anyone can view bids" ON bids;
DROP POLICY IF EXISTS "Authenticated users can create bids" ON bids;
DROP POLICY IF EXISTS "Users can view their own profile" ON user_profiles;
DROP POLICY IF EXISTS "Users can update their own profile" ON user_profiles;
DROP POLICY IF EXISTS "Users can insert their own profile" ON user_profiles;

-- Create policies for auctions
CREATE POLICY "Anyone can view auctions" ON auctions FOR SELECT USING (true);
CREATE POLICY "Authenticated users can create auctions" ON auctions 
    FOR INSERT WITH CHECK (auth.role() = 'authenticated');
CREATE POLICY "Authenticated users can update auctions" ON auctions 
    FOR UPDATE USING (auth.role() = 'authenticated');

-- Create policies for bids
CREATE POLICY "Anyone can view bids" ON bids FOR SELECT USING (true);
CREATE POLICY "Authenticated users can create bids" ON bids 
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Create policies for user_profiles
CREATE POLICY "Users can view their own profile" ON user_profiles 
    FOR SELECT USING (auth.uid() = id);
CREATE POLICY "Users can update their own profile" ON user_profiles 
    FOR UPDATE USING (auth.uid() = id);
CREATE POLICY "Users can insert their own profile" ON user_profiles 
    FOR INSERT WITH CHECK (auth.uid() = id);

-- Function to handle user profile creation
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.user_profiles (id, email, full_name)
    VALUES (NEW.id, NEW.email, NEW.raw_user_meta_data->>'full_name');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to automatically create user profile when user signs up
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Function to update bid count when a bid is placed
CREATE OR REPLACE FUNCTION public.update_user_bid_count()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE user_profiles 
    SET total_bids = total_bids + 1,
        updated_at = NOW()
    WHERE id = NEW.user_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to update user bid count
DROP TRIGGER IF EXISTS on_bid_created ON bids;
CREATE TRIGGER on_bid_created
    AFTER INSERT ON bids
    FOR EACH ROW EXECUTE FUNCTION public.update_user_bid_count();

-- Function to update auction updated_at timestamp
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update auction updated_at
DROP TRIGGER IF EXISTS update_auctions_updated_at ON auctions;
CREATE TRIGGER update_auctions_updated_at
    BEFORE UPDATE ON auctions
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- Function to handle placing a bid atomically
CREATE OR REPLACE FUNCTION place_bid(
    auction_id_param BIGINT,
    bid_amount DECIMAL(10,2),
    user_id_param UUID
)
RETURNS TABLE (
    success BOOLEAN,
    message TEXT,
    auction_id BIGINT
) AS $$
DECLARE
    current_auction auctions%ROWTYPE;
    user_email_param TEXT;
BEGIN
    -- Select the auction and lock the row for this transaction
    SELECT * INTO current_auction FROM auctions WHERE id = auction_id_param FOR UPDATE;

    -- Get user email
    SELECT email INTO user_email_param FROM auth.users WHERE id = user_id_param;

    -- Check if auction exists
    IF current_auction IS NULL THEN
        RETURN QUERY SELECT FALSE, 'Auction not found.', NULL::BIGINT;
        RETURN;
    END IF;

    -- Check if auction is active
    IF current_auction.status != 'active' THEN
        RETURN QUERY SELECT FALSE, 'Auction is not active.', NULL::BIGINT;
        RETURN;
    END IF;

    -- Check if auction has ended
    IF current_auction.end_time < NOW() THEN
        RETURN QUERY SELECT FALSE, 'Auction has ended.', NULL::BIGINT;
        RETURN;
    END IF;

    -- Check if bid is high enough
    IF bid_amount <= current_auction.current_bid OR bid_amount < current_auction.minimum_bid THEN
        RETURN QUERY SELECT FALSE, 'Bid amount must be higher than the current bid and the minimum bid.', NULL::BIGINT;
        RETURN;
    END IF;

    -- Update auction with the new bid
    UPDATE auctions
    SET 
        current_bid = bid_amount,
        bid_count = current_auction.bid_count + 1,
        updated_at = NOW()
    WHERE id = auction_id_param;

    -- Insert the new bid into the bids table
    INSERT INTO bids (auction_id, user_id, user_email, amount)
    VALUES (auction_id_param, user_id_param, user_email_param, bid_amount);

    -- Return success
    RETURN QUERY SELECT TRUE, 'Bid placed successfully.', auction_id_param;

EXCEPTION
    WHEN OTHERS THEN
        RETURN QUERY SELECT FALSE, 'An error occurred while placing the bid.', NULL::BIGINT;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Insert sample auctions for testing
INSERT INTO auctions (title, description, current_bid, minimum_bid, end_time, status, bid_count) VALUES
(
    'Vintage Rolex Submariner',
    'Rare 1970s Rolex Submariner in excellent condition. A true collector''s piece with original documentation.',
    15000.00,
    10000.00,
    NOW() + INTERVAL '2 hours',
    'active',
    12
),
(
    'MacBook Pro M3 Max',
    'Brand new MacBook Pro with M3 Max chip, 32GB RAM, 1TB SSD. Still in original packaging.',
    2800.00,
    2000.00,
    NOW() + INTERVAL '4 hours',
    'active',
    8
),
(
    'Tesla Model S Plaid',
    '2023 Tesla Model S Plaid with autopilot, low mileage, perfect condition. Fastest production car.',
    95000.00,
    80000.00,
    NOW() + INTERVAL '6 hours',
    'active',
    25
),
(
    'Rare Pokemon Cards Collection',
    'Complete set of 1st Edition Base Set Pokemon cards including Charizard. All cards in mint condition.',
    12500.00,
    8000.00,
    NOW() + INTERVAL '3 hours',
    'active',
    18
),
(
    'Limited Edition Gaming PC',
    'Custom built gaming PC with RTX 4090, i9-13900K, 64GB RAM, liquid cooling. RGB everything!',
    4500.00,
    3000.00,
    NOW() + INTERVAL '5 hours',
    'active',
    14
),
(
    'Vintage Guitar Collection',
    '1959 Gibson Les Paul Standard in pristine condition. One of the most sought-after guitars.',
    35000.00,
    25000.00,
    NOW() + INTERVAL '8 hours',
    'active',
    31
);

-- Create a view for auction statistics
CREATE OR REPLACE VIEW auction_stats AS
SELECT 
    a.id,
    a.title,
    a.current_bid,
    a.minimum_bid,
    a.bid_count,
    a.status,
    a.end_time,
    CASE 
        WHEN a.end_time < NOW() THEN 'expired'
        WHEN a.end_time < NOW() + INTERVAL '1 hour' THEN 'ending_soon'
        ELSE 'active'
    END as time_status,
    EXTRACT(EPOCH FROM (a.end_time - NOW())) as seconds_remaining,
    COALESCE(MAX(b.amount), a.minimum_bid) as highest_bid,
    COUNT(DISTINCT b.user_id) as unique_bidders
FROM auctions a
LEFT JOIN bids b ON a.id = b.auction_id
GROUP BY a.id, a.title, a.current_bid, a.minimum_bid, a.bid_count, a.status, a.end_time;

-- Create a function to get auction leaderboard
CREATE OR REPLACE FUNCTION get_auction_leaderboard(auction_id_param BIGINT)
RETURNS TABLE (
    user_email TEXT,
    max_bid DECIMAL(10,2),
    bid_count BIGINT,
    last_bid_time TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        b.user_email,
        MAX(b.amount) as max_bid,
        COUNT(b.id) as bid_count,
        MAX(b.created_at) as last_bid_time
    FROM bids b
    WHERE b.auction_id = auction_id_param
    GROUP BY b.user_email, b.user_id
    ORDER BY MAX(b.amount) DESC, MAX(b.created_at) DESC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create a function to get user auction history
CREATE OR REPLACE FUNCTION get_user_auction_history(user_id_param UUID)
RETURNS TABLE (
    auction_id BIGINT,
    auction_title TEXT,
    user_max_bid DECIMAL(10,2),
    current_winning_bid DECIMAL(10,2),
    is_winning BOOLEAN,
    auction_status TEXT,
    auction_end_time TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        a.id as auction_id,
        a.title as auction_title,
        MAX(b.amount) as user_max_bid,
        a.current_bid as current_winning_bid,
        (MAX(b.amount) = a.current_bid) as is_winning,
        a.status as auction_status,
        a.end_time as auction_end_time
    FROM auctions a
    INNER JOIN bids b ON a.id = b.auction_id
    WHERE b.user_id = user_id_param
    GROUP BY a.id, a.title, a.current_bid, a.status, a.end_time
    ORDER BY a.end_time DESC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;