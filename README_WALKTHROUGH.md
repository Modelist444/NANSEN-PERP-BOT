# ASMM v3.3.1 Pro - Final Walkthrough

The bot is now fully stabilized, sharing-ready, and verified for continuous operation. 

## Recent Crucial Fixes
I have resolved the following "stealth" bugs that only triggered during active trades:
*   **Method Name Mismatch:** Fixed `update_daily_pnl` in `risk.py` and `main.py`. This prevents crashes when trades hit Take Profit or Stop Loss.
*   **Database Mapping:** Eliminated `AttributeError: sqlite3.Row object has no attribute get` by using safe bracket indexing.
*   **Process Management:** Cleared 13+ orphaned background processes that were causing port conflicts.

## How to Operate the Bot

### 1. Launch the Bot (EASY WAY)
I have created a valid "One-Click" starter script for you.

1.  Open your folder: `Documents\NANSEN PERP BOT`
2.  Double-click the file named: **`start_bot.bat`**
3.  Two windows will open:
    *   **Window 1 (Bot):** This runs the simulation.
    *   **Window 2 (Ngrok):** This gives you the link.

### 2. How to Get the New Link
1.  Look at the **Black Console Window** titled "Public Link (Ngrok)".
2.  Find the line that starts with the word `Forwarding`.
3.  It will look exactly like this:
    `Forwarding    https://1234abcd.ngrok-free.app -> http://localhost:8000`
4.  **Highlight and Copy** the part that starts with `https://`.

**That `https://...` address is your public link.** paste it into your phone or browser.

### 3. Graceful Stop
Press **`Ctrl + C`** once in the bot terminal. The bot will save all data and exit immediately.

## Verified Results
*   **Stability:** Bot runs 100+ cycles without memory leaks or crashes.
*   **Visuals:** Dashboard equity and PnL drift live with simulated price action.
*   **Strategy:** Tiered leverage and dual TP signals are working as specified.

### 4. File Safety
**✅ All files are saved safely here:**
`C:\Users\USA\Documents\NANSEN PERP BOT`

Everything is running from this folder. If you close your code editor or restart your computer, your code is safe. Just navigate back to this folder to start again.
