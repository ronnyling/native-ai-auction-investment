# <% tp.date.now("YYYY-MM-DD") %> — Auction Daily

## Auction This Week
```dataview
TABLE reserve_price, bmv_pct, state, city, auction_date, status
FROM "Properties"
WHERE days_to_auction <= 7 AND status != "passed"
SORT auction_date ASC
```

## New Today
```dataview
TABLE reserve_price, bmv_pct, state, city, property_type, auction_date
FROM "Properties"
WHERE scrape_date = date(today)
SORT reserve_price ASC
```

## Re-auctions (Price Dropped)
```dataview
TABLE reserve_price, original_reserve, total_price_drop, auction_count, city, auction_date
FROM "Properties"
WHERE auction_count > 1 AND status != "passed"
SORT total_price_drop DESC
```

## My Shortlist
```dataview
TABLE reserve_price, bmv_pct, city, auction_date, action_needed, rating
FROM "Properties"
WHERE contains(list("shortlisted","visiting","bid"), status)
SORT auction_date ASC
```
