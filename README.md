BTC/USD Momentum & Tape Reader (Streamlit Dashboard)

This is a real-time trading analysis dashboard designed to generate high-conviction Buy/Sell signals for the BTC/USD pair. It employs a two-layer strategy: an M15 Technical Setup (trend filter) combined with simulated, short-term "Tape Reading" microstructure confirmations.
The front-end is designed with a professional, clean light theme for clear visualization of active signals and market bias.

Key Features

-M15 Trend Filter: Simulates technical analysis (MACD/RSI proxies) to determine the prevailing 15-minute market bias (Bullish or Bearish setup).
-Real-Time Tape Confirmation: Simulates four key market microstructure events (e.g., Absorption, Cascading Cancels) that confirm the larger M15 trend.
-Confluence Signal: Generates an actionable BUY or SELL signal only when the M15 trend aligns with one or more active Tape Confirmation triggers.
-Live Data: Fetches the latest BTC/USD price directly from the Kraken API every 60 seconds.
-Signal History: Logs the last 30 generated signals for quick review.

Technology Stack

Language: Python
Framework: Streamlit (for web dashboard)
Data Source: Kraken Public Ticker API

How to Run Locally

To run this dashboard on your machine, follow these steps:

Clone the repository:
git clone [your-repository-url]
cd tape-reader-project


Install dependencies:
This project requires streamlit and requests.

pip install streamlit pandas requests


Run the application:

streamlit run tape_reading_15m_btc_momentum.py


The application will launch in your default browser at http://localhost:8501.
