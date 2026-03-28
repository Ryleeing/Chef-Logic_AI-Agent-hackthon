import streamlit as st
import httpx
import json
import math
import datetime
from urllib.parse import quote
from collections import defaultdict

# ── CONFIG ───────────────────────────────────────────────────────────────────
LUMA_BASE = "https://luma-mock-server.vercel.app"
LUMA_HEADERS = {"x-luma-api-key": "demo-key"}

# Unit prices for Aaltoes internal cost estimation
ITEM_PRICES = {
    "Pizza (regular)":                  3.50,
    "Pizza (vegetarian)":               3.50,
    "Pizza (vegan)":                    3.80,
    "Snack bags (mixed)":               1.20,
    "Energy drinks":                    1.50,
    "Soft drinks (cans)":               0.90,
    "Water bottles":                    0.60,
    "Fruit (pieces)":                   0.40,
    "Coffee (cups est.)":               0.30,
    "Bread rolls":                      0.50,
    "Ham / Turkey slices (portions)":   0.80,
    "Cheese slices (portions)":         0.70,
    "Butter portions":                  0.20,
    "Gluten-free bread rolls":          1.20,
    "Vegan cheese slices (portions)":   1.00,
    "Paper plates":                     0.10,
    "Napkins":                          0.05,
}

# S-kaupat search terms optimized for Finnish compound word matching
SKAUPAT_SEARCH = {
    "Pizza (regular)":                  "pizza",
    "Pizza (vegetarian)":               "kasvispizza",     
    "Pizza (vegan)":                    "vegaanipizza",    
    "Snack bags (mixed)":               "sipsi",           
    "Energy drinks":                    "energiajuoma",
    "Soft drinks (cans)":               "virvoitusjuoma tölkki",
    "Water bottles":                    "vesipullo",       
    "Fruit (pieces)":                   "hedelmä",        
    "Coffee (cups est.)":               "kahvi",
    "Bread rolls":                      "sämpylä",
    "Ham / Turkey slices (portions)":   "kinkkuviipale",  
    "Cheese slices (portions)":         "juustoviipale",  
    "Butter portions":                  "voi",
    "Gluten-free bread rolls":          "gluteeniton sämpylä",
    "Vegan cheese slices (portions)":   "vegaanijuusto",    
    "Paper plates":                     "pahvilautanen",
    "Napkins":                          "lautasliina",
}

# Standard event patterns for Aaltoes operations
FOOD_TEMPLATES = {
    "Pitch / Demo Night": {
        "Pizza (regular)":    2.5,
        "Pizza (vegetarian)": 0.8,
        "Soft drinks (cans)": 1.5,
        "Water bottles":      1.0,
        "Paper plates":       3.0,
        "Napkins":            4.0,
    },
    "Workshop / Hackathon": {
        "Snack bags (mixed)": 1.0,
        "Energy drinks":      0.8,
        "Soft drinks (cans)": 1.2,
        "Water bottles":      2.0,
        "Fruit (pieces)":     1.5,
        "Coffee (cups est.)": 2.0,
    },
    "Fireside Chat / Speaker": {
        "Bread rolls":                    2.0,
        "Ham / Turkey slices (portions)": 1.5,
        "Cheese slices (portions)":       1.5,
        "Butter portions":                1.0,
        "Soft drinks (cans)":             1.0,
        "Water bottles":                  1.0,
        "Paper plates":                   2.0,
        "Napkins":                        3.0,
    },
    "Table Chat / Exclusive": {
        "Pizza (regular)":    3.0,
        "Pizza (vegetarian)": 1.0,
        "Soft drinks (cans)": 1.5,
        "Water bottles":      1.0,
        "Paper plates":       3.0,
        "Napkins":            4.0,
    },
    "General / Other": {
        "Snack bags (mixed)": 1.0,
        "Soft drinks (cans)": 1.2,
        "Water bottles":      1.5,
        "Fruit (pieces)":     1.0,
    },
}

# Baseline no-show rates used if historical check-in data is missing
BASE_NO_SHOW_RATES = {
    "Pitch / Demo Night":      0.28,
    "Workshop / Hackathon":    0.20,
    "Fireside Chat / Speaker": 0.32,
    "Table Chat / Exclusive":  0.15,
    "General / Other":         0.30,
}

# ── LUMA API INTEGRATION ──────────────────────────────────────────────────────
@st.cache_data(ttl=120)
def fetch_events():
    """Fetch events and hunt for check-in metrics across various JSON layers."""
    try:
        r = httpx.get(f"{LUMA_BASE}/api/v1/calendar/list-events", headers=LUMA_HEADERS, timeout=10)
        data = r.json()
        entries = data.get("entries", [])
        events = []
        for e in entries:
            ev = e.get("event", e)
            
            # Robust extraction of check-in data to bypass Luma schema inconsistencies
            chk_count = (
                ev.get("checked_in_count") or 
                ev.get("checkin_count") or 
                ev.get("guest_metrics", {}).get("checked_in") or 0
            )
            
            events.append({
                "id":               ev.get("id", ""),
                "name":             ev.get("name", "Unnamed event"),
                "start_at":         ev.get("start_at", ""),
                "guest_count":      ev.get("guest_count") or ev.get("guests_count") or 0,
                "checked_in_count": chk_count,
            })
        return sorted(events, key=lambda x: x["start_at"], reverse=True)[:20]
    except Exception as ex:
        st.error(f"Could not fetch events: {ex}")
        return []

@st.cache_data(ttl=120)
def fetch_guests(event_id):
    """Fetch guests for a specific event with a pagination safety valve."""
    guests, cursor = [], None
    page_count = 0
    max_pages = 50  # Prevent infinite loops in mock API environments

    try:
        while page_count < max_pages:
            params = {"event_id": event_id, "approval_status": "approved", "pagination_limit": 100}
            if cursor:
                params["pagination_cursor"] = cursor
            
            r = httpx.get(f"{LUMA_BASE}/api/v1/event/get-guests", headers=LUMA_HEADERS, params=params, timeout=10)
            data = r.json()
            guests += data.get("entries", [])
            
            if not data.get("has_more"):
                break
                
            cursor = data.get("next_cursor")
            page_count += 1
            
        return guests
    except Exception:
        return []

# ── LOGIC STEP 1: PREDICTIVE ANALYTICS ────────────────────────────────────────
def predict_attendance(event_type, registered, past_events=[]):
    """Calculate no-show rate dynamically based on historical behavior."""
    dynamic_rate = None
    relevant_events = [e for e in past_events if e.get("guest_count", 0) > 0] 
    
    if relevant_events:
        total_registered = 0
        total_checked_in = 0
        
        for e in relevant_events:
            reg = e.get("guest_count", 0)
            chk = e.get("checked_in_count", 0) 
            
            if reg > 0 and chk > 0:
                total_registered += reg
                total_checked_in += chk
                
        if total_registered > 0:
            dynamic_rate = 1 - (total_checked_in / total_registered)

    is_dynamic = (dynamic_rate is not None and dynamic_rate > 0)
    final_rate = dynamic_rate if is_dynamic else BASE_NO_SHOW_RATES.get(event_type, 0.30)
    expected = round(registered * (1 - final_rate))
    return expected, round(final_rate, 2), is_dynamic

# ── LOGIC STEP 2: FUZZY DIETARY PARSING ───────────────────────────────────────
def extract_dietary(guests):
    """Fuzzy scan entire guest objects for keywords to bypass missing schema keys."""
    counts = defaultdict(int)
    total_with_data = 0
    
    for entry in guests:
        # Full object text scan for maximum reliability against inconsistent APIs
        raw_dump = json.dumps(entry).lower()
        
        found = False
        if any(w in raw_dump for w in ["vegan", "vegaani"]):
            counts["vegan"] += 1
            found = True
        if any(w in raw_dump for w in ["vegetarian", "vegetariaani", "veggie", "kasvis"]):
            counts["vegetarian"] += 1
            found = True
        if any(w in raw_dump for w in ["gluten", "celiac", "keliakia", "gluteeniton"]):
            counts["gluten-free"] += 1
            found = True
        
        if found:
            total_with_data += 1

    # Heuristic: Trust parsed data if >5% coverage, else trigger inference fallback
    is_data_reliable = total_with_data > (len(guests) * 0.05)
    return dict(counts), total_with_data if is_data_reliable else 0

def infer_dietary_fallback(expected):
    """Fallback: Standard Aaltoes statistical distribution for food restrictions."""
    return {
        "vegetarian":  math.ceil(expected * 0.10),
        "vegan":       math.ceil(expected * 0.03),
        "gluten-free": math.ceil(expected * 0.05),
    }

# ── LOGIC STEP 3: FOOD ENGINE ──────────────────────────────────────────────────
def calculate_order(event_type, expected, dietary_counts):
    """Map headcount to food items and apply dietary substitutions."""
    template = FOOD_TEMPLATES.get(event_type, FOOD_TEMPLATES["General / Other"])
    items = {}
    notes = []

    for item, per_person in template.items():
        items[item] = math.ceil(expected * per_person)

    vegan       = dietary_counts.get("vegan", 0)
    vegetarian  = dietary_counts.get("vegetarian", 0)
    gluten_free = dietary_counts.get("gluten-free", 0)

    # Substitution Logic for Pizzas and Sandwiches
    if vegan > 0:
        if "Pizza (regular)" in items:
            convert = math.ceil(vegan * 2.5)
            items["Pizza (regular)"] = max(0, items["Pizza (regular)"] - convert)
            items["Pizza (vegan)"]   = convert
            notes.append(f"Swapped {convert} regular slices for vegan options.")
        if "Ham / Turkey slices (portions)" in items:
            items["Ham / Turkey slices (portions)"] = max(0, items["Ham / Turkey slices (portions)"] - vegan)
            items["Vegan cheese slices (portions)"] = items.get("Vegan cheese slices (portions)", 0) + vegan

    if vegetarian > 0:
        if "Pizza (regular)" in items:
            convert = math.ceil(vegetarian * 1.5)
            items["Pizza (regular)"]    = max(0, items["Pizza (regular)"] - convert)
            items["Pizza (vegetarian)"] = items.get("Pizza (vegetarian)", 0) + convert

    if gluten_free > 0:
        if "Bread rolls" in items:
            items["Bread rolls"]             = max(0, items["Bread rolls"] - gluten_free * 2)
            items["Gluten-free bread rolls"] = gluten_free * 2

    items = {k: v for k, v in items.items() if v > 0}
    total_cost = sum(qty * ITEM_PRICES.get(name, 1.50) for name, qty in items.items())
    return items, round(total_cost, 2), notes

def skaupat_url(item_name):
    """Direct deep-link to S-kaupat search results."""
    search_term = SKAUPAT_SEARCH.get(item_name, item_name)
    return f"https://www.s-kaupat.fi/hakutulokset?queryString={quote(search_term)}"

# ── UI: STREAMLIT APP ──────────────────────────────────────────────────────────
st.set_page_config(page_title="Aaltoes Food Agent", page_icon="🍕", layout="centered")
st.title("🍕 Aaltoes Food Ordering Agent")
st.caption("AI-Powered Event Logistics: From Luma Guests to S-kaupat Cart.")

with st.sidebar:
    st.header("Agent Capabilities")
    st.markdown("**1. Data Trigger**\nConnects to Luma API for real-time guest lists.")
    st.markdown("**2. Predictive Planning**\nCalculates dynamic no-show rates from history.")
    st.markdown("**3. Fuzzy Parsing**\nDeep-scans JSON objects for dietary restrictions.")
    st.markdown("**4. Automated Sourcing**\nGenerates deep-links and finance reports.")

# ── SECTION 1: EVENT SELECTION ──
st.subheader("1. Select event from Luma")
with st.spinner("Syncing with Luma API..."):
    events = fetch_events()

if not events:
    st.error("Luma API unreachable.")
    st.stop()

event_options = {f"{e['name']} ({e['start_at'][:10]})": e for e in events}
selected_label = st.selectbox("Active Event", list(event_options.keys()))
selected_event = event_options[selected_label]
event_type = st.selectbox("Event Pattern", list(FOOD_TEMPLATES.keys()))

# ── SECTION 2: ATTENDANCE PREDICTION ──
st.subheader("2. Attendance prediction")
registered_default = max(int(selected_event.get("guest_count") or 0), 20)
registered = st.number_input("Registered guests", min_value=1, value=registered_default)

expected, no_show_rate, is_dynamic = predict_attendance(event_type, registered, events)

# Delta tracking for session state (UX improvement)
if "prev_expected" not in st.session_state: st.session_state.prev_expected = expected
delta = expected - st.session_state.prev_expected
st.session_state.prev_expected = expected

col1, col2, col3 = st.columns(3)
col1.metric("Registered", registered)
rate_label = "No-show (Dynamic)" if is_dynamic else "No-show (Baseline)"
col2.metric(rate_label, f"{int(no_show_rate * 100)}%")
col3.metric("Expected Attendance", expected, delta=int(delta) if delta != 0 else None)

with st.expander("Prediction Model Details"):
    if is_dynamic:
        st.info("✅ **Dynamic memory active:** Using historical Luma check-in metrics.")
    else:
        st.warning("⚠️ **Baseline Active:** Mock API lacks check-in metrics. Falling back to presets.")

# ── SECTION 3: DIETARY ANALYSIS ──
st.subheader("3. Dietary restrictions")
with st.spinner("Parsing guest sign-up forms..."):
    guests = fetch_guests(selected_event["id"])

dietary_counts, guests_with_data = extract_dietary(guests)
using_fallback = (guests_with_data == 0)

if not using_fallback:
    st.success(f"✅ Extracted data for {guests_with_data} guests via fuzzy parsing.")
    cols = st.columns(len(dietary_counts))
    for i, (k, v) in enumerate(dietary_counts.items()):
        cols[i].metric(k.title(), v)
else:
    st.warning("⚠️ Mock API lacks dietary fields. Applying statistical inference model.")
    dietary_counts = infer_dietary_fallback(expected)
    cols = st.columns(len(dietary_counts))
    for i, (k, v) in enumerate(dietary_counts.items()):
        cols[i].metric(f"{k.title()} (est.)", v)

with st.expander("Manual Override"):
    col1, col2, col3, col4 = st.columns(4)
    dietary_counts["vegan"]       = col1.number_input("Vegan",       min_value=0, value=dietary_counts.get("vegan", 0))
    dietary_counts["vegetarian"]  = col2.number_input("Vegetarian",  min_value=0, value=dietary_counts.get("vegetarian", 0))
    dietary_counts["gluten-free"] = col3.number_input("Gluten-free", min_value=0, value=dietary_counts.get("gluten-free", 0))
    dietary_counts["halal"]       = col4.number_input("Halal",       min_value=0, value=dietary_counts.get("halal", 0))

# ── SECTION 4: CART & FINANCE EXPORT ──
st.subheader("4. S-kaupat Shopping Cart")

items, total_cost, notes = calculate_order(event_type, expected, dietary_counts)

# Visual feedback for reactive updates
current_time = datetime.datetime.now().strftime("%H:%M:%S")
st.toast(f"Synchronized with inputs at {current_time}!", icon="✅")

# Cart Table
for name, qty in items.items():
    price = ITEM_PRICES.get(name, 1.50)
    subtotal = qty * price
    url = skaupat_url(name)
    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
    col1.markdown(f"[{name}]({url})")
    col2.markdown(f"**{qty}**")
    col3.markdown(f"€{price:.2f}")
    col4.markdown(f"€{subtotal:.2f}")

st.divider()
st.info(f"💶 **Estimated Total: €{total_cost:.2f}**")


st.markdown("### 📥 Export")
export = {
    "event":              selected_event["name"],
    "event_type":         event_type,
    "registered":         registered,
    "no_show_rate":       no_show_rate,
    "expected_attendees": expected,
    "dietary_source":     "sign-up data" if not using_fallback else "past event inference",
    "dietary_counts":     dietary_counts,
    "shopping_list":      [{"name": k, "quantity": v, "skaupat_url": skaupat_url(k)} for k, v in items.items()],
    "estimated_cost_eur": total_cost,
    "notes":              notes,
}

st.download_button(
    label="Download order as JSON",
    data=json.dumps(export, indent=2, ensure_ascii=False),
    file_name=f"food_order_{selected_event['id']}.json",
    mime="application/json",
)

# --- Quick Win: Finance & Reimbursement Report ---
st.markdown("### 📊 Accounting & Reimbursement")
st.caption("Generate a clean CSV report for the Aaltoes finance team.")

# Build CSV string manually to avoid Pandas dependency
csv_header = "Item,Quantity,Unit Price (EUR),Total Cost (EUR)\n"
csv_rows = [f"{k},{v},{ITEM_PRICES.get(k, 1.50):.2f},{v * ITEM_PRICES.get(k, 1.50):.2f}" for k, v in items.items()]
csv_data = csv_header + "\n".join(csv_rows)

st.download_button(
    label="Download Finance Report (CSV)",
    data=csv_data.encode('utf-8'),
    file_name=f"reimbursement_{selected_event['id']}.csv",
    mime="text/csv",
    type="secondary"
)