# 🌾 FarmVault

**FarmVault** is an AI-powered digital twin platform for post-harvest agricultural produce management. It simulates the real-time journey of farm produce — from harvest through storage to market — using synthetic IoT sensor data, decay modeling, price forecasting, and scenario simulation, giving farmers and aggregators actionable recommendations to reduce spoilage and maximize revenue.

---

## ✨ Key Features

- **Digital Twin Engine** — Live virtual representation of produce batches and storage units, continuously updated from simulated IoT sensor streams (temperature, humidity, ethylene levels).
- **Decay & Freshness Modeling** — AI-driven decay curves predict shelf life and quality degradation based on storage conditions and produce type.
- **Price Forecasting** — Time-series forecasting of mandi (market) prices to identify optimal sell windows.
- **Anomaly Detection** — Automatic detection of abnormal sensor readings (cold-chain breaks, spoilage risk) with real-time alerts.
- **Scenario Simulation** — "What-if" analysis to compare outcomes of different storage/selling strategies (e.g., sell now vs. cold-store for 5 days).
- **Explainable AI** — Human-readable justifications behind every recommendation.
- **Real-Time Dashboard** — WebSocket-driven live updates across produce twins, market feeds, and alerts.
- **Interactive Visualizations** — Timeline views, decay charts, price charts, and side-by-side scenario comparisons.

---

## 🏗️ Architecture

```
┌─────────────────┐     REST + WebSocket     ┌──────────────────┐
│   React Frontend │ ◄───────────────────────► │  FastAPI Backend │
└─────────────────┘                            └──────────────────┘
                                                        │
                        ┌───────────────────────────────┼───────────────────────────────┐
                        ▼                                ▼                                ▼
                ┌───────────────┐              ┌──────────────────┐              ┌────────────────┐
                │  Twin Core     │              │   AI Models       │              │  IoT Simulator  │
                │  (state mgmt)  │              │ (decay, price,    │              │ (sensor + market│
                │                │              │  anomaly, optim.) │              │  event streams) │
                └───────────────┘              └──────────────────┘              └────────────────┘
```

See [`docs/architecture.md`](docs/architecture.md) for the full breakdown and [`docs/workflow.md`](docs/workflow.md) for the end-to-end data flow.

---

## 🛠️ Tech Stack

| Layer      | Technology                                   |
|------------|-----------------------------------------------|
| Backend    | Python, FastAPI, Uvicorn, WebSockets           |
| AI/ML      | scikit-learn, pandas, NumPy, statsmodels       |
| Frontend   | React, Vite, Recharts/Chart.js                 |
| Data       | CSV-based synthetic datasets (decay curves, mandi prices, storage conditions) |
| Realtime   | Native WebSocket event bus                     |

---

## 📁 Project Structure

```
farmvault/
├── backend/
│   ├── app/
│   │   ├── api/            # Route handlers
│   │   ├── models/         # DB/domain models
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── services/       # Business logic
│   │   ├── twin_core/      # Digital twin engine
│   │   ├── ai_models/      # ML models
│   │   ├── iot_simulator/  # Synthetic sensor/market data
│   │   ├── websocket/      # Realtime manager
│   │   ├── utils/          # Shared utilities
│   │   └── data/           # Seed/reference datasets
│   └── requirements.txt
├── frontend/
│   └── src/                # React application
├── docs/                   # Architecture, workflow, API, demo docs
└── screenshots/            # UI screenshots
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+ and npm
- Git

### 1. Clone the repository

```bash
git clone https://github.com/<your-org>/farmvault.git
cd farmvault
```

### 2. Backend setup

```bash
cd backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp ../.env.example ../.env    # configure environment variables
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000` and interactive docs at `http://localhost:8000/docs`.

### 3. Frontend setup

```bash
cd frontend
npm install
npm run dev
```

The app will be available at `http://localhost:5173`.

### 4. Environment Variables

Copy `.env.example` to `.env` in the project root and fill in the required values before starting the backend. See that file for full descriptions of each variable.

---

## 📡 API Overview

| Endpoint prefix       | Purpose                                  |
|------------------------|-------------------------------------------|
| `/api/produce`          | CRUD for produce batches                  |
| `/api/market`            | Market/mandi price data                   |
| `/api/twin`               | Digital twin state and updates            |
| `/api/prediction`          | Decay, price, and anomaly predictions   |
| `/api/simulation`           | Scenario simulation engine             |
| `/api/dashboard`             | Aggregated dashboard data             |
| `/ws`                          | Real-time WebSocket event stream    |

Full API reference: [`docs/api_documentation.md`](docs/api_documentation.md)

---

## 🧪 Running Tests

```bash
cd backend
pytest
```

---

## 📖 Documentation

- [Architecture](docs/architecture.md)
- [Workflow](docs/workflow.md)
- [API Documentation](docs/api_documentation.md)
- [Presentation Notes](docs/presentation_notes.md)
- [Demo Script](docs/demo_script.md)

---

## 🗺️ Roadmap

- [ ] Persist historical twin snapshots for trend analysis
- [ ] Integrate real IoT hardware feeds alongside the simulator
- [ ] Multi-user auth and role-based access (farmer / trader / admin)
- [ ] Mobile-responsive dashboard
- [ ] Export scenario reports as PDF

---

## 🤝 Contributing

Contributions are welcome. Please open an issue to discuss significant changes before submitting a pull request.

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Push and open a PR

---

## 📄 License

This project is licensed under the MIT License. See `LICENSE` for details.