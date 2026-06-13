# Rubix Curriculum Automation Engine

This project automates the process of selecting and saving disciplines and specializations for internship availabilities on the Rubix ONE platform based on data provided in an Excel file.

## Prerequisites & Installation

1. Open this folder in VS Code.
2. Open a new terminal inside VS Code and install the required dependencies along with the Playwright browsers:
   ```bash
   pip install -r requirements.txt
   playwright install
   ```
   *(If you don't have a `requirements.txt`, you will generally need `playwright`, `pandas`, `openpyxl`, and `flask`.)*

## Excel Template & Preparation

You must use the exact format provided in the template file: `E:\Rubix_Avai_update\data_input_template.xlsx`. 
*Note: Please download the template if it is provided to you as a link.*

**Steps to prepare your data:**
1. Open your main source file and the `data_input_template.xlsx` file.
2. Simply copy and paste the rows of the availabilities you want to update into the template.
3. **CRITICAL:** There is one extra required field called `_id` (which represents the Availability ID). If it is not present in your main source file, please ask a senior team member to add it directly into the main file for your ease!

## How to Run

### Step 1: First-Time Login (Session Capture)

1. Run the main script in your terminal:
   ```bash
   python main.py
   ```
2. The menu will appear. **Select option `1`**.
3. A browser window will open. Log in to your Rubix account.
4. Once you are successfully logged in, **click on "Availability"**. 
5. The page and browser will close automatically. Your session is now saved!

### Step 2: Start the Engine & Ingest Data

1. Run the main script again:
   ```bash
   python main.py
   ```
2. This time, **select option `2`**.
3. Open your web browser and go to the local dashboard: [http://localhost:5000](http://localhost:5000)
4. On the dashboard, under **Controls**:
   - Click on **Choose File** and select your prepared Excel file.
   - Click the **Upload & Ingest** button.
   - Click the **Start Engine** button.

### Handling Failures

- The engine will process the queued records one by one. You can monitor the progress via the Live Logs and the Success/Failed cards on the dashboard.
- **In case of any failures**, wait for all other records to complete processing first.
- Once the queue is finished, simply re-upload the same Excel file (or just an Excel file containing only the failed ones), click **Upload & Ingest**, and start the engine again. The system will automatically detect the failed records, update them, and re-queue them for processing!
