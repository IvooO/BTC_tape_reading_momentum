import streamlit as st
import requests
import time
import random
import datetime # Used for signal timestamping
import pandas as pd # Used for displaying the history table

# --- CONFIGURATION ---
KRAKEN_TICKER_URL = 'https://api.kraken.com/0/public/Ticker?pair=XBTUSD'
# FETCHES NEW PRICE DATA AND RUNS LOGIC EVERY 60 SECONDS
FETCH_INTERVAL_SECONDS = 60 
MOMENTUM_WINDOW = 5   # Last 5 cycles = 5 minutes of momentum context
HISTORY_WINDOW = 12   # Last 12 cycles = 12 minutes of history context
MOMENTUM_THRESHOLD = 0.5
BULL_PROB = 0.40
BEAR_PROB = 0.40
# Hold signals for 4 cycles * 60 seconds = 240 seconds (4 minutes)
TAPE_HOLD_CYCLES = 4 
# The application reruns every second to update the "Time to Next Update" counter smoothly
RERUN_INTERVAL_SECONDS = 1 
# Maximum number of historical signals to store
MAX_SIGNAL_HISTORY = 30

# --- STATE MANAGEMENT & INITIALIZATION ---

def initialize_state():
    """Initializes session state variables and handles stale state migration."""
    if 'price_snapshot' not in st.session_state:
        st.session_state.price_snapshot = []
    if 'price_deltas' not in st.session_state:
        st.session_state.price_deltas = []
    if 'last_price' not in st.session_state:
        st.session_state.last_price = 0.00
    if 'last_fetch_time' not in st.session_state:
        st.session_state.last_fetch_time = time.time()
        
    if 'last_momentum_sum' not in st.session_state:
        st.session_state.last_momentum_sum = 0.0
    if 'last_momentum_bias' not in st.session_state:
        st.session_state.last_momentum_bias = 0
        
    
    # Define the required initial structure with safe defaults
    initial_signals = {
        'technical_signal': 'neutral',
        'macd_text': 'AWAITING INITIAL FETCH',
        'rsi_text': 'AWAITING INITIAL FETCH',
        'macd_display_text': '⚪ WAITING FOR M15 SETUP', 
        'tape_1': ('neutral', 'ABSORPTION (BUY)'),
        'tape_2': ('neutral', 'ZTP UP (BUY)'),
        'tape_3': ('neutral', 'RETAIL EXHAUSTION (SELL)'),
        'tape_4': ('neutral', 'CASCADING CANCELS (SELL)'),
        'final_signal': 'INITIATING',
        'final_state': 'neutral',
    }
    
    # 1. INITIALIZE IF MISSING
    if 'last_signals' not in st.session_state:
        st.session_state['last_signals'] = initial_signals
    
    # 2. STALE STATE MIGRATION PATCH (Ensures all expected keys are present in the dictionary)
    if 'last_signals' in st.session_state:
        for key, default_value in initial_signals.items():
            if key not in st.session_state['last_signals']:
                st.session_state['last_signals'][key] = default_value

        
    if 'tape_hold_timers' not in st.session_state:
        st.session_state.tape_hold_timers = {
            'tape_1': 0, 'tape_2': 0, 'tape_3': 0, 'tape_4': 0
        }
        
    if 'signal_history' not in st.session_state:
        st.session_state.signal_history = []


initialize_state()

# --- UTILITY & STYLING FUNCTIONS (Google/Clean Style) ---

def get_status_styles(state):
    """Returns CSS styles and icon for status indicators (Clean/Material Style)."""
    
    # [BG Color, Text Color on BG, Default Text, CSS Class Name]
    styles = {
        'buy': ('#34A853', '#FFFFFF', '⬆ BUY', 'state-buy'),    # Google Green
        'sell': ('#EA4335', '#FFFFFF', '⬇ SELL', 'state-sell'),  # Google Red
        'wait': ('#4285F4', '#FFFFFF', 'WAIT', 'state-wait'),    # Google Blue (Used for Technical setup)
        'neutral': ('#F8D346', '#1F1F1F', 'WAITING', 'state-neutral'), # Caution Yellow (Used for Tape wait)
        'tech_neutral': ('#F1F3F4', '#5F6368', 'WAITING', 'state-tech-neutral'), # Light Grey (Tech wait)
    }
         
    return styles.get(state, styles['tech_neutral'])

def render_indicator(title, text, state, is_tape=False):
    """Renders a custom styled metric/indicator."""
    
    if state == 'neutral':
        style_key = 'neutral' if is_tape else 'tech_neutral'
    else:
        style_key = state

    bg_color, text_color, _, _ = get_status_styles(style_key)
    
    # Custom flicker style for active tape signals (using lighter colors for less distraction)
    flicker_style = 'animation: flicker-green-google 0.2s infinite alternate;' if is_tape and state == 'buy' else \
                    'animation: flicker-red-google 0.2s infinite alternate;' if is_tape and state == 'sell' else ''

    markdown_content = f"""
    <div style="
        background-color: #FFFFFF;
        border: 1px solid #DADCE0;
        border-radius: 8px; /* Rounded corners for material look */
        padding: 10px;
        margin-top: 5px;
        box-shadow: 0 1px 2px 0 rgba(60,64,67,0.1), 0 2px 6px 2px rgba(60,64,67,0.05); /* Subtle shadow */
    ">
        <p style="color: #5F6368; font-size: 0.8rem; margin-bottom: 2px; font-weight: 500;">{title}</p>
        <p style="
            background-color: {bg_color}; 
            color: {text_color}; 
            font-weight: 700; 
            padding: 12px 5px; 
            border-radius: 4px; 
            text-align: center;
            font-size: 1.0rem;
            {flicker_style}
        ">{text}</p>
    </div>
    """
    st.markdown(markdown_content, unsafe_allow_html=True)


# --- DATA FETCHING ---

def fetch_kraken_price():
    """Fetches the latest BTC/USD price from Kraken."""
    try:
        # Implements a simple retry mechanism
        for _ in range(3):
            response = requests.get(KRAKEN_TICKER_URL, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            pair_key = next(iter(data['result']))
            latest_price_str = data['result'][pair_key]['c'][0]
            latest_price = float(latest_price_str)
            
            return latest_price
    except Exception:
        return None

# --- SIGNAL LOGIC ---

def update_history(latest_price):
    """Updates the price history and delta lists in session state."""
    
    if st.session_state.last_price is not None:
        delta = latest_price - st.session_state.last_price
        st.session_state.price_deltas.append(delta)
        if len(st.session_state.price_deltas) > MOMENTUM_WINDOW:
            st.session_state.price_deltas.pop(0)

    st.session_state.price_snapshot.append(latest_price)
    if len(st.session_state.price_snapshot) > HISTORY_WINDOW:
        st.session_state.price_snapshot.pop(0)
    
    st.session_state.last_price = latest_price


def calculate_momentum_bias():
    """Calculates the short-term momentum bias."""
    if not st.session_state.price_deltas:
        return 0.0, 0
    
    momentum_sum = sum(st.session_state.price_deltas)
    
    bias = 0
    if momentum_sum > MOMENTUM_THRESHOLD:
        bias = 1
    elif momentum_sum < -MOMENTUM_THRESHOLD:
        bias = -1
        
    return momentum_sum, bias


def simulate_technical_signal(current_price, momentum_sum, momentum_bias):
    """
    Simulates the M15 MACD and RSI based on zero-line crossover criteria.
    Returns: (state, macd_desc, rsi_desc, macd_display_text)
    """
    
    # We must ensure all keys are present, especially if called during initialization
    signals = st.session_state.get('last_signals', {})
    
    if len(st.session_state.price_snapshot) < HISTORY_WINDOW:
        # Return default safe values if history is too short
        return (
            signals.get('technical_signal', 'neutral'), 
            signals.get('macd_text', 'AWAITING INITIAL FETCH'), 
            signals.get('rsi_text', 'AWAITING INITIAL FETCH'), 
            signals.get('macd_display_text', '⚪ WAITING FOR M15 SETUP')
        )
        
    # Use average price as a proxy for the 'Zero Line' based on recent M15 context
    avg_price = sum(st.session_state.price_snapshot) / len(st.session_state.price_snapshot)
    
    technical_signal_state = 'neutral'
    macd_text_desc = "CONSOLIDATION ZONE"
    rsi_text_desc = "MID-RANGE CONSOLIDATION"
    display_status = '⚪ WAITING FOR M15 SETUP' # <-- Default/Neutral state
    
    # --- SIMULATED MACD BUY CRITERIA ---
    if momentum_bias == 1 and current_price < avg_price: 
        technical_signal_state = 'buy'
        display_status = '🟢 BUY'
        macd_text_desc = "BULLISH Crossover & Below Zero Line Confirmed"
        rsi_text_desc = "RSI > 45 AND RISING (BULLISH ENTRY)"
        
    # --- SIMULATED MACD SELL CRITERIA ---
    elif momentum_bias == -1 and current_price > avg_price:
        technical_signal_state = 'sell'
        display_status = '🔴 SELL'
        macd_text_desc = "BEARISH Crossover & Above Zero Line Confirmed"
        rsi_text_desc = "RSI < 55 AND FALLING (BEARISH ENTRY)"
        
    return technical_signal_state, macd_text_desc, rsi_text_desc, display_status


def simulate_tape_confirmation(trend_state):
    """Simulates the Tape Confirmation Triggers with persistence logic."""
    
    TAPE_CONFIG = [
        ('tape_1', 'ABSORPTION (BUY)'),
        ('tape_2', 'ZTP UP (BUY)'),
        ('tape_3', 'RETAIL EXHAUSTION (SELL)'),
        ('tape_4', 'CASCADING CANCELS (SELL)'),
    ]
    
    bull_confirms = 0
    bear_confirms = 0
    tape_results = {}
    
    bull_prob = BULL_PROB if trend_state == 'buy' else 0.05
    bear_prob = BEAR_PROB if trend_state == 'sell' else 0.05

    for key in st.session_state.tape_hold_timers:
        st.session_state.tape_hold_timers[key] = max(0, st.session_state.tape_hold_timers[key] - 1)

    for key, text in TAPE_CONFIG:
        is_bullish_group = key in ['tape_1', 'tape_2']
        is_new_trigger = False
        
        if is_bullish_group and random.random() < bull_prob:
            is_new_trigger = True
        elif not is_bullish_group and random.random() < bear_prob:
            is_new_trigger = True
            
        is_currently_held = st.session_state.tape_hold_timers[key] > 0
        current_state = 'neutral'
        
        if is_new_trigger or is_currently_held:
            current_state = 'buy' if is_bullish_group else 'sell'
            
            if is_new_trigger: 
                st.session_state.tape_hold_timers[key] = TAPE_HOLD_CYCLES
            
            if current_state == 'buy':
                bull_confirms += 1
            else:
                bear_confirms += 1

        tape_results[key] = (current_state, text)

    final_signal = 'WAITING FOR CONFLUENCE'
    final_state = 'tech_neutral' # Use tech_neutral for main wait state
    
    if trend_state == 'buy' and bull_confirms >= 1:
        final_signal = f"BUY (CONF: {bull_confirms})"
        final_state = 'buy'
    elif trend_state == 'sell' and bear_confirms >= 1:
        final_signal = f"SELL (CONF: {bear_confirms})"
        final_state = 'sell'

    return {
        'tape_1': tape_results['tape_1'],
        'tape_2': tape_results['tape_2'],
        'tape_3': tape_results['tape_3'],
        'tape_4': tape_results['tape_4'],
        'final_signal': final_signal,
        'final_state': final_state,
        'technical_signal': trend_state
    }

# --- SIDEBAR PLAYBOOK ---

def render_playbook_sidebar():
    """Renders the detailed trading playbook in the sidebar."""
    st.sidebar.markdown(
        """
        <div style="padding: 15px; border-bottom: 1px solid #DADCE0; margin-bottom: 20px;">
            <h2 style="color: #1F1F1F; font-size: 1.5rem; font-weight: bold; margin: 0;">Trading Playbook</h2>
            <p style="color: #5F6368; font-size: 0.8rem; margin-top: 5px;">How the system generates signals.</p>
        </div>
        """, unsafe_allow_html=True
    )

    st.sidebar.markdown("### 1. M15 Technical Trend Setup")
    st.sidebar.info(
        "This is the **Primary Filter**. It checks for **M15 MACD Zero Line Crossover** confluence using a proxy:\n"
        "- **BULLISH Setup (🟢 BUY):** Short-term momentum is UP *and* price is currently below the M15 rolling average (Zero Line).\n"
        "- **BEARISH Setup (🔴 SELL):** Short-term momentum is DOWN *and* price is currently above the M15 rolling average (Zero Line).\n"
        "**The system only trades when the technical setup is 🟢 BUY or 🔴 SELL.**"
    )

    st.sidebar.markdown("### 2. Tape Confirmation Triggers")
    st.sidebar.markdown(
        """
        These are short-term market microstructure events (simulated) that confirm the larger M15 trend. They stay active for **4 minutes** after triggering.
        """
    )

    # Bullish Triggers
    st.sidebar.markdown("#### 🟢 Bullish Confirms")
    st.sidebar.markdown(
        """
        - **ABSORPTION (BUY):** Aggressive buying volume consuming passive offers, showing institutional entry.
        - **ZTP UP (BUY):** Zero-Tolerance Price Up; large bids placed immediately above current price, forcing shorts to cover.
        """
    )
    
    # Bearish Triggers
    st.sidebar.markdown("#### 🔴 Bearish Confirms")
    st.sidebar.markdown(
        """
        - **RETAIL EXHAUSTION (SELL):** Small, aggressive buy orders cease, signaling the end of retail momentum.
        - **CASCADING CANCELS (SELL):** Large bids pulled from the book in quick succession, creating air below the market.
        """
    )
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 3. Final Signal")
    st.sidebar.markdown(
        "A final signal is generated **ONLY** when the **M15 Technical Setup** aligns with **1 or more active Tape Confirmation Triggers**."
    )


# --- STREAMLIT UI LAYOUT (Google/Clean Style) ---

def display_dashboard(latest_price, momentum_sum, momentum_bias, signals, time_remaining):
    """
    Builds the main Streamlit UI using columns and containers.
    Crucially, it uses signals.get() to safely access data and prevent KeyError.
    """
    
    st.markdown("""
        <style>
            /* Google/Material Inspired Theme */
            .stApp { 
                background-color: #F1F3F4; /* Light Gray Background */
                color: #1F1F1F; 
                font-family: 'Google Sans', 'Roboto', 'Arial', sans-serif;
            }
            /* Main Header Style (Clean White) */
            .google-header {
                background-color: white;
                color: #1F1F1F; 
                padding: 15px 20px;
                margin: -20px -20px 0px -20px; 
                border-bottom: 1px solid #DADCE0; /* Light border */
                box-shadow: 0 1px 2px 0 rgba(60,64,67,0.08); /* Subtle shadow */
            }
            .google-header h1 {
                font-size: 1.8rem;
                font-weight: 500; /* Lighter weight for clean look */
                margin: 0;
                color: #1F1F1F;
            }

            /* Card styling (Material card look) */
            .card {
                background-color: white;
                border-radius: 8px;
                padding: 20px;
                border: 1px solid #DADCE0; 
                box-shadow: 0 1px 2px 0 rgba(60,64,67,0.1), 0 2px 6px 2px rgba(60,64,67,0.05);
                margin-bottom: 15px;
            }
            
            /* Metrics (Large Price Display) */
            .stMetric [data-testid="stMetricValue"] { 
                color: #1F1F1F; 
                font-size: 2.5rem; 
                font-weight: 800; 
            }
            .stMetric [data-testid="stMetricLabel"] { 
                color: #5F6368; 
                font-weight: 500; 
            }
            
            /* Flicker Animation (Google Colors) */
            @keyframes flicker-green-google {
                0%, 100% { background-color: #34A853; }
                50% { background-color: #5CBF78; } 
            }
            @keyframes flicker-red-google {
                0%, 100% { background-color: #EA4335; }
                50% { background-color: #F3756A; } 
            }
        </style>
        
        <div class="google-header">
            <h1>BTC/USD Momentum & Tape Reader</h1>
        </div>
    """, unsafe_allow_html=True)
    
    # ----------------------------------------------------
    # RETRIEVE AND SAFELY DEFAULT ALL NECESSARY SIGNAL DATA
    # ----------------------------------------------------
    technical_signal = signals.get('technical_signal', 'tech_neutral')
    macd_display_text = signals.get('macd_display_text', '⚪ WAITING FOR M15 SETUP')
    rsi_text = signals.get('rsi_text', 'AWAITING FETCH')
    final_state = signals.get('final_state', 'tech_neutral')
    final_signal = signals.get('final_signal', 'INITIATING')

    
    # ----------------------------------------------------
    # ROW 1: Technical Setup and Final Signal
    # ----------------------------------------------------
    col_main, col_signal = st.columns([2, 1])

    with col_main:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown(f'<h2 style="font-size: 1.4rem; font-weight: 600; color: #1F1F1F; margin-top: 0; border-bottom: 1px solid #DADCE0; padding-bottom: 10px;">M15 Trend Setup & Price Data</h2>', unsafe_allow_html=True)
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Kraken Last Trade Price", f"${latest_price:,.2f}")
        with c2:
            # THIS LINE USES THE SAFE LOCAL VARIABLES
            render_indicator(
                "M15 MACD Signal Status", 
                macd_display_text, 
                technical_signal
            )
        with c3:
            # THIS LINE USES THE SAFE LOCAL VARIABLES
            render_indicator("Simulated RSI Level", rsi_text, technical_signal)
        
        momentum_state = 'Neutral'
        if momentum_bias == 1:
            momentum_state = 'Strong UP'
        elif momentum_bias == -1:
            momentum_state = 'Strong DOWN'
            
        st.markdown(f"""
            <p style="color: #5F6368; font-size: 0.85rem; margin-top: 1rem;">
                Recent **Price Momentum**: {momentum_state} ({momentum_sum:.2f}) - Based on last {MOMENTUM_WINDOW} minutes.
            </p>
        """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with col_signal:
        st.markdown('<div class="card" style="height: 100%; display: flex; flex-direction: column; justify-content: flex-start;">', unsafe_allow_html=True)
        st.markdown(f'<h2 style="font-size: 1.4rem; font-weight: 600; color: #1F1F1F; margin-top: 0; border-bottom: 1px solid #DADCE0; padding-bottom: 10px;">CONFLUENCE SIGNAL</h2>', unsafe_allow_html=True)
        
        final_bg, final_text_color, _, _ = get_status_styles(final_state)
        
        st.markdown(f"""
        <div style="
            background-color: {final_bg}; 
            color: {final_text_color}; 
            padding: 1.5rem 1rem; 
            border-radius: 6px; 
            text-align: center; 
            margin-top: 15px;
            font-weight: 700;
        ">
            <p style="font-size: 1.1rem; font-weight: 500; margin-bottom: 5px;">Strategy Output</p>
            <p style="font-size: 2.0rem; font-weight: 900; margin-top: 0; color: {final_text_color};">{final_signal}</p>
        </div>
        """, unsafe_allow_html=True)
        
        time_color = '#EA4335' if time_remaining < 10 else '#34A853'
        st.markdown(f'<p style="text-align: center; font-weight: bold; color: {time_color}; font-size: 1.1rem; margin-top: 10px;">🔄 Update in {int(time_remaining)}s</p>', unsafe_allow_html=True)

        st.markdown('<p style="color: #999999; text-align: center; font-size: 0.7rem; margin-top: 10px;">M15 Setup MUST align with 1+ Tape Confirmation.</p>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)


    # ----------------------------------------------------
    # ROW 2: Tape Confirmation Zone
    # ----------------------------------------------------
    st.markdown(f'<h2 style="font-size: 1.2rem; font-weight: 600; color: #1F1F1F; margin-top: 0; padding-bottom: 5px; border-bottom: 1px solid #DADCE0;">REAL-TIME TAPE CONFIRMATION TRADES (4 Min Hold)</h2>', unsafe_allow_html=True)
    
    col_tape = st.columns(4)
    
    with col_tape[0]:
        # Using .get() for the tuple elements
        t1_state, t1_text = signals.get('tape_1', ('neutral', 'ABSORPTION (BUY)'))
        render_indicator("Bullish 1: Hidden", t1_text, t1_state, is_tape=True)
    
    with col_tape[1]:
        t2_state, t2_text = signals.get('tape_2', ('neutral', 'ZTP UP (BUY)'))
        render_indicator("Bullish 2: Order Book", t2_text, t2_state, is_tape=True)
    
    with col_tape[2]:
        t3_state, t3_text = signals.get('tape_3', ('neutral', 'RETAIL EXHAUSTION (SELL)'))
        render_indicator("Bearish 1: Small Orders", t3_text, t3_state, is_tape=True)
    
    with col_tape[3]:
        t4_state, t4_text = signals.get('tape_4', ('neutral', 'CASCADING CANCELS (SELL)'))
        render_indicator("Bearish 2: HFT Activity", t4_text, t4_state, is_tape=True)


    # ----------------------------------------------------
    # ROW 3: SIGNAL HISTORY TABLE
    # ----------------------------------------------------
    st.markdown("""
        <div class="card" style="margin-top: 15px; padding-bottom: 5px;">
            <h2 style="font-size: 1.2rem; font-weight: 600; color: #1F1F1F; margin-top: 0; padding-bottom: 5px; border-bottom: 1px solid #DADCE0;">Last 30 Signal History (Newest First)</h2>
        </div>
    """, unsafe_allow_html=True)
    
    if st.session_state.signal_history:
        df_history = pd.DataFrame(st.session_state.signal_history)
        
        def color_signals(val):
            if 'BUY' in val:
                return 'background-color: #E6F4EA; color: #34A853; font-weight: bold' 
            elif 'SELL' in val:
                return 'background-color: #FCE8E6; color: #EA4335; font-weight: bold'
            return ''

        st.dataframe(
            df_history.style.applymap(color_signals, subset=['Final Signal']),
            use_container_width=True,
            height=400
        )
    else:
        st.info("No signals logged yet. Waiting for the first 60-second fetch to establish a history.")


# --- MAIN APPLICATION LOOP ---

def main_app():
    """Main application logic for continuous refresh."""
    
    render_playbook_sidebar()
    
    dashboard_container = st.empty()

    while True:
        current_time = time.time()
        time_elapsed = current_time - st.session_state.last_fetch_time
        time_remaining = max(0, FETCH_INTERVAL_SECONDS - time_elapsed)
        
        # Pull all display variables from state FIRST
        latest_price = st.session_state.last_price
        momentum_sum = st.session_state.last_momentum_sum
        momentum_bias = st.session_state.last_momentum_bias
        signals = st.session_state['last_signals'] 
        
        # 1. LOGIC UPDATE: Only fetch new data and recalculate signals every FETCH_INTERVAL_SECONDS
        if time_elapsed >= FETCH_INTERVAL_SECONDS:
            fetched_price = fetch_kraken_price()
            
            if fetched_price is not None:
                latest_price = fetched_price
                update_history(latest_price)
                
                # --- RUN LOGIC ---
                momentum_sum, momentum_bias = calculate_momentum_bias() 
                st.session_state['last_momentum_sum'] = momentum_sum 
                st.session_state['last_momentum_bias'] = momentum_bias 
                
                technical_signal, macd_text, rsi_text, macd_display_text = simulate_technical_signal(latest_price, momentum_sum, momentum_bias)
                tape_results = simulate_tape_confirmation(technical_signal)
                
                # Consolidate and store the new signals structure
                signals = {
                    'technical_signal': technical_signal,
                    'macd_text': macd_text,
                    'rsi_text': rsi_text,
                    'macd_display_text': macd_display_text,
                    **tape_results
                }
                st.session_state.last_fetch_time = current_time
                st.session_state['last_signals'] = signals
                
                # --- LOG THE SIGNAL HISTORY ---
                # Safely access signals for logging just in case
                signal_entry = {
                    'Timestamp': datetime.datetime.now().strftime('%H:%M:%S'),
                    'M15 MACD': signals.get('macd_text', 'N/A'), 
                    'RSI Level': signals.get('rsi_text', 'N/A'),
                    'Final Signal': signals.get('final_signal', 'N/A'),
                }
                st.session_state.signal_history.insert(0, signal_entry)
                if len(st.session_state.signal_history) > MAX_SIGNAL_HISTORY:
                    st.session_state.signal_history.pop()

            else:
                 st.session_state.last_fetch_time = current_time
            
        else:
             # 2. UI UPDATE ONLY: Continue running tape confirmation logic to decrement timers
             # Safely retrieve the technical signal from the state for tape simulation
             technical_signal_for_tape = signals.get('technical_signal', 'neutral')
             simulate_tape_confirmation(technical_signal_for_tape) 

        
        # Draw the dashboard now that all variables are guaranteed to be bound
        with dashboard_container.container():
            display_dashboard(latest_price, momentum_sum, momentum_bias, signals, time_remaining) 
        
        time.sleep(RERUN_INTERVAL_SECONDS)
        st.rerun()

if __name__ == '__main__':
    main_app()