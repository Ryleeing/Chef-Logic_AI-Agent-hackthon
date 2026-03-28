
# 🍕 Chef-Logic[AI-Agent-hackthon] - Aaltoes Food Ordering Agent

A deterministic, end-to-end procurement agent built for the Aaltoes AI Agent Hackathon. 

This agent automates the event catering workflow by syncing with the Luma API, predicting actual attendance, inferring dietary needs, and generating a pre-filled S-kaupat cart alongside finance reimbursement reports.

##  Architecture & Tradeoffs

This agent uses a deterministic workflow rather than an LLM, and can be replaced by a Large Language Model (LLM) such as Claude 3.5 Opus once API access is restored

* **Human-in-the-Loop Procurement:** Instead of fragile web scrapers executing unauthorized payments, the agent generates deep-links to S-kaupat search results. The human operator verifies the final cart and executes the payment.
* **Predictive No-Show Modeling:** Analyzes historical check-in metrics from past Luma events to calculate dynamic drop-off rates. If historical data is missing (e.g., in mock environments), it degrades gracefully to a validated statistical baseline.
* **Fuzzy Dietary Parsing:** To handle inconsistent Mock API data, the agent deep-scans JSON payloads for dietary keywords, ensuring no guest is missed even when API keys are missing.

## Agentic Workflow

1.  **Trigger (Sync):** Connects to the Luma API to fetch active events and registered guest lists (with a 5,000 guest pagination safety valve).
2.  **Perception (Parse):** Extracts headcount and fuzzy-matches dietary restrictions (Vegan, GF, Halal, etc.).
3.  **Planning (Optimize):** Maps the event type to a specific food template (e.g., Pitch Night vs. Workshop). Dynamically substitutes standard items for dietary alternatives (e.g., swapping regular pizza slices for vegan options) to optimize the budget.
4.  **Action (Execute):** * Generates a one-click S-kaupat shopping cart interface.
    * Exports a JSON manifest for system logging.
    * Exports a clean CSV Finance Report for immediate Aaltoes reimbursement.

