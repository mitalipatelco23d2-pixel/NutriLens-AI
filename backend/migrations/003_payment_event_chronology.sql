ALTER TABLE subscriptions
ADD COLUMN IF NOT EXISTS last_provider_event_at TIMESTAMPTZ;
