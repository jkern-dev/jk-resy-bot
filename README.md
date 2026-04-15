# Restaurant Reservation Bot

Automated reservation sniping for **Resy** and **OpenTable**. The bot continuously scans for open tables at your favorite restaurants across the next several weekends and books them automatically.

Both bots run via Docker and share the same config structure: a YAML file with default preferences plus per-weekend overrides.

---

## Quick Start

1. Copy the appropriate sample config into `config_files/`:
   - **Resy**: `cp config_files/sample_resy_config.yaml config_files/resy_config.yaml`
   - **OpenTable**: `cp config_files/sample_opentable_config.yaml config_files/opentable_config.yaml`

2. Edit the config file with your credentials and preferences.

3. Start the bot(s):
   ```bash
   # Resy bot only
   docker compose up --build resy-bot

   # OpenTable bot only
   docker compose up --build opentable-bot

   # Both bots
   docker compose up --build

   # Detached mode
   docker compose up --build -d
   ```

4. View logs:
   ```bash
   # Resy bot logs
   docker compose logs -f resy-bot

   # OpenTable bot logs
   docker compose logs -f opentable-bot
   ```

   Or use the web UI:
   - Resy: `http://localhost:8995`
   - OpenTable: `http://localhost:8996`

---

## Resy Bot

### How It Works

The Resy bot uses the [Resy API](http://subzerocbd.info/) to scan restaurants from your **Hit List** (favorites) for available reservations on upcoming weekends (next 8 weeks by default). It runs every 5 seconds and books matching slots automatically.

Optionally, the bot can pull its config from Dropbox for remote updates. Set `local_config_only: True` in your `startup_config.yaml` to use a local file only.

### Setup

1. Create `config_files/startup_config.yaml` (copy from `sample_startup_config.yaml`).
2. Create `config_files/resy_config.yaml` (copy from `sample_resy_config.yaml`).
3. Set your credentials, timezone, and preferences.

Remember to have a credit card on file in your Resy account — some reservations require one for late cancellation / no-show policies.

### Finding Your Resy API Key

1. Log into Resy in your browser.
2. Open DevTools: right-click → Inspect → Network tab.
3. Search for any restaurant and look for a request to `api.resy.com` (e.g. `search`).
4. Find the `Authorization` header — it looks like `ResyAPI api_key="your_api_key"`.
5. Copy the key into your config file.

### Features

- Only books tables within your acceptable time window
- Skips restaurants you've visited within the last 90 days (configurable via `min_days_since_last_visit`)
- Skips restaurants where you have an upcoming reservation
- Won't book non-refundable reservations unless explicitly allowed
- Only books prepaid reservations if there's >24 hours to cancel without penalty

---

## OpenTable Bot

### How It Works

The OpenTable bot uses OpenTable's GraphQL API to scan your **Favorites/Wishlist** for available reservations on upcoming weekends. It automatically locks and books matching slots.

On startup, Playwright launches a headless browser to log into your OpenTable account and extract fresh session cookies. These cookies are used for all subsequent API calls. The bot refreshes cookies automatically every 4 hours.

### Setup

1. Create `config_files/opentable_config.yaml` (copy from `sample_opentable_config.yaml`).
2. Fill in your OpenTable credentials:
   - `email` — your OpenTable login email
   - `password` — your OpenTable password (enables automatic cookie refresh)
   - `first_name`, `last_name`, `phone` — required for completing reservations

### Restaurant Source

By default, the bot fetches restaurants from your **OpenTable Favorites** (wishlist). No manual restaurant list needed.

To use a static list instead, add a `restaurants` section to your config:
```yaml
restaurants:
  - id: 1403569
    name: "La Grande Boucherie NYC"
```

You can also override restaurants per-weekend or per-date in the config.

### Config Options

| Option | Description | Default |
|--------|-------------|---------|
| `preferred_reservation_time` | Target time in 24h format | `"19:00"` |
| `acceptable_delta_in_minutes` | Window before/after preferred time | `60` |
| `min_days_since_last_visit` | Skip restaurants booked within this many days | `90` |
| `sleep_time_in_seconds` | Delay between polling cycles | `5` |
| `party_size` | Number of guests | `2` |
| `timezone` | Your timezone | `"America/New_York"` |
| `weeks_to_process` | How many weeks ahead to scan | `8` |

### Weekend Overrides

Override settings for specific weekends:
```yaml
weekend_overrides:
  this_weekend:
    ignore: True
  next_weekend:
    party_size: 4
  fourth_weekend:
    restaurants:
      - id: 123456
        name: "Carbone"
```

### Specific Date Bookings

Target specific dates:
```yaml
specific_dates:
  2025-07-04:
    restaurants:
      - id: 123456
        name: "Carbone"
```

### Features

- Automatically fetches restaurants from your OpenTable Favorites
- Automated cookie refresh via Playwright (no manual cookie management)
- Uses `curl_cffi` with Chrome TLS impersonation to bypass bot detection
- Tracks booking history to enforce `min_days_since_last_visit`
- Full booking flow: availability check → slot lock → reservation confirmation

---

## Deploying to a Server

See [DEPLOY.md](DEPLOY.md) for instructions on deploying to a remote VPS.
