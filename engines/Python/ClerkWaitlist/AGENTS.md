# Clerk Waitlist Engine

Read-only access to Clerk's Backend API waitlist endpoints.

## Setup

Set `CLERK_SECRET_KEY` to a Clerk secret key from **Clerk Dashboard → API Keys**.
Never commit the key.

## Routing

- Use `status` to verify configuration.
- Use `list_entries` for browsing, filtering, and pagination.
- Use `get_entry` when an exact waitlist entry ID is known.
- Use `summarize` for a compact operational snapshot.

This engine intentionally does not invite, reject, create, or delete entries.
