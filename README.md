# Disaster Response Multi-Agent System

![System Architecture](https://img.shields.io/badge/Status-Prototype-yellow)
![Python](https://img.shields.io/badge/Python-3.9+-blue)
![License](https://img.shields.io/badge/License-MIT-green)

An autonomous multi-agent system for real-time flood disaster response coordination in Dhaka, Bangladesh.

## 🎯 Project Overview

This system uses specialized AI agents to:
- **Monitor** environmental conditions and social media for flood threats
- **Analyze** data using LLMs and computer vision
- **Predict** flood progression using spatial and temporal models
- **Coordinate** rescue resource allocation and dispatch

**Capstone Project** - Undergraduate Final Year
**Team Size:** 4 members
**Duration:** 5 months (1 month prototype + 4 months production)

## 🏗️ Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                    Agent 1: Environmental Intelligence       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Weather    │  │    Social    │  │  Satellite   │     │
│  │   Monitor    │  │    Media     │  │   Imagery    │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            │                                 │
│                    ┌───────▼────────┐                       │
│                    │  Data Fusion   │                       │
│                    │  & Enrichment  │                       │
│                    └───────┬────────┘                       │
│                            │                                 │
│                    ┌───────▼────────┐                       │
│                    │    Spatial     │                       │
│                    │    Analysis    │                       │
│                    └───────┬────────┘                       │
│                            │                                 │
│                    ┌───────▼────────┐                       │
│                    │   Prediction   │                       │
│                    │     Model      │                       │
│                    └───────┬────────┘                       │
└────────────────────────────┼────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │   Message Bus   │
                    │     (Redis)     │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
┌────────▼────────┐ ┌────────▼────────┐ ┌───────▼────────┐
│    Agent 2:     │ │    Agent 3:     │ │   Agent 4:     │
│    Distress     │ │    Resource     │ │   Dispatch     │
│  Intelligence   │ │   Management    │ │ Optimization   │
└─────────────────┘ └─────────────────┘ └────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.9 or higher
- Docker Desktop installed and running
- API keys (see setup guide below)

### 1. Clone Repository
```bash
git clone https://github.com/yourusername/disaster-response-system.git
cd disaster-response-system
```

### 2. Setup Environment
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables
```bash
# Copy example environment file
cp .env.example .env

# Edit .env and add your API keys
nano .env  # or use any text editor
```

Add your API keys to `.env`:
```env
OPENWEATHER_API_KEY=your_openweather_key_here
TWITTER_BEARER_TOKEN=your_twitter_bearer_token_here
OPENAI_API_KEY=your_openai_key_here
```

### 4. Start Docker Services
```bash
# Start PostgreSQL and Redis
docker-compose up -d

# Verify services are running
docker-compose ps
```

### 5. Initialize Database
```bash
# Run database initialization script
python scripts/init_database.py
```

### 6. Test API Connections
```bash
# Verify all APIs are working
python scripts/test_apis.py
```

### 7. Run Agent 1 (Environmental Intelligence)
```bash
# Option A: Run with real APIs (uses your API quota)
python -m src.agents.agent_1_environmental.main

# Option B: Run with simulated data (recommended for prototype)
python scripts/run_simulation.py
```

## 📊 Running the Prototype Demo

For your defense presentation, use simulated mode:
```bash
# Generate simulated data
python data/simulated/generate_weather.py
python data/simulated/generate_social.py

# Run 3-hour simulation
python scripts/run_simulation.py --duration 180 --scenario urban_flood
```

This will:
- Simulate a flooding event in Dhaka
- Generate realistic social media reports
- Show Agent 1 processing data in real-time
- Display threat maps and predictions
- Save metrics for presentation

## 🧪 Testing
```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_agent_1.py -v

# Run with coverage
pytest --cov=src tests/
```

## 📖 Documentation

- [API Setup Guide](docs/API_SETUP_GUIDE.md) - Detailed instructions for obtaining all API keys
- [Architecture Documentation](docs/ARCHITECTURE.md) - System design and agent interactions
- [Deployment Guide](docs/DEPLOYMENT.md) - Production deployment instructions

## 🎓 Academic Context

**University:** [Your University Name]
**Course:** CSE499 - Capstone Project
**Supervisor:** [Supervisor Name]
**Defense Date:** [Date]

### Project Phases

- **Phase 1 (Completed):** Requirements analysis and system design
- **Phase 2 (Current - 1 month):** Prototype development and defense presentation
- **Phase 3 (4 months):** Full system implementation and deployment

## 📈 Success Metrics

The system demonstrates:
1. **Response Time:** < 5 minutes from distress signal to dispatch
2. **Resource Optimization:** 75%+ team utilization efficiency
3. **Prediction Accuracy:** 85%+ threat level prediction accuracy
4. **Coverage:** Real-time monitoring of 300+ km² urban area

## 🤝 Team Members

1. [Member 1 Name] - Agent 1 & 2 Development
2. [Member 2 Name] - Agent 3 & 4 Development  
3. [Member 3 Name] - Database & Infrastructure
4. [Member 4 Name] - Frontend Dashboard & Testing

## 📝 License

MIT License - See [LICENSE](LICENSE) file

## 🙏 Acknowledgments

- OpenWeatherMap for weather data
- Twitter for social media access
- OpenAI for NLP capabilities
- Bangladesh Department of Disaster Management for domain expertise

## 📧 Contact

For questions about this project:
- Email: your.email@university.edu
- Project Repository: [GitHub Link]