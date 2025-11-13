# Project Setup and Usage Guide

This guide will walk you through setting up the Python environment, running the application, and using the mooring data generator API.

## Prerequisites

- Python 3.x installed on your system
- pip (Python package installer)

## Setup Instructions

### 1. Create a Python Virtual Environment

```bash
# Create a virtual environment named 'venv'
python3 -m venv venv
```

### 2. Activate the Virtual Environment

**On Linux/Mac:**
```bash
source venv/bin/activate
```

**On Windows:**
```bash
venv\Scripts\activate
```

### 3. Install Requirements

```bash
pip install -r requirements.txt
```

## Running the Application

### 4. Start the Main Application

In your current terminal, run:

```bash
python3 main.py
```

This will start the server (typically on `http://127.0.0.1:8000`).

### 5. Run the Mooring Data Generator

Open a **new terminal window** and activate the virtual environment again:

```bash
# Activate virtual environment
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate  # Windows

# Run the mooring data generator
mooring-data-generator http://127.0.0.1:8000/receive/
```

## Using the API

### 6. Find a Ship ID

Navigate to the data endpoint in your browser or use curl:

```bash
# Browser
http://127.0.0.1:8000/api/data

# Or using curl
curl http://127.0.0.1:8000/api/data
```

This will display a list of available ship IDs.

### 7. View Ship Data

Once you have a ship ID, access the specific ship's data:

```bash
# Browser
http://127.0.0.1:8000/ships/{ship_id}

# Or using curl
curl http://127.0.0.1:8000/ships/{ship_id}
```

Replace `{ship_id}` with the actual ship ID you obtained from step 6.

## Example Workflow

```bash
# Terminal 1
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py

# Terminal 2 (new terminal)
source venv/bin/activate
mooring-data-generator http://127.0.0.1:8000/receive/

# Browser or Terminal 3
# Visit: http://127.0.0.1:8000/api/data
# Get ship_id (e.g., "ship_12345")
# Visit: http://127.0.0.1:8000/ships/ship_12345
```

## Troubleshooting

- **Virtual environment not activating**: Make sure you're in the project directory
- **Port already in use**: Check if another application is using port 8000 and stop it, or modify the port in your configuration
- **Package installation errors**: Ensure pip is up to date: `pip install --upgrade pip`
- **mooring-data-generator not found**: Verify it's installed in requirements.txt and properly installed

## Deactivating the Virtual Environment

When you're done working, deactivate the virtual environment:

```bash
deactivate
```