# Lead Personalization System

A Python automation tool that generates personalized WhatsApp messages for tradespeople leads by analyzing their Google Maps reviews.

## Overview

This system reads leads from a Google Sheet, fetches and analyzes their Google Maps reviews, then uses AI to generate personalized WhatsApp messages. The personalized messages are written back to a separate sheet for outreach campaigns.

## How It Works

### 1. Lead Data Collection

The system reads lead information from a configured Google Sheet worksheet. Each lead contains:

- ID (Google Maps place ID)
- Business name
- Contact information (phone, email)
- Social media profiles
- Physical address

### 2. Review Fetching

For each unprocessed lead:

- Uses the Apify API with Google Maps Reviews Scraper
- Fetches up to 20 reviews per business using the place ID
- Retrieves review text, reviewer name, and title

### 3. Review Analysis

The AI review agent processes the fetched reviews to:

- Extract the business owner's name from review context
- Summarize key themes and patterns across reviews
- Identify positive and negative feedback
- Highlight unique business characteristics

This analysis uses the top 5 reviews to create a concise 2-4 sentence summary.

### 4. Message Personalization

The AI personalization agent generates a WhatsApp message with:

- Personal greeting using the owner's first name
- Relevant pain point specific to their trade
- Brief introduction to the AI answering service
- Low-commitment call to action
- Conversational British tone

The message is crafted to feel like a business owner reaching out to another, emphasizing the financial impact of missed calls.

### 5. Output Management

Generated personalizations are written to the `outreach_personalisation` worksheet with:

- Lead ID
- Phone number
- Personalized DM opener

The system tracks which leads have been processed to avoid duplication on subsequent runs.

## Architecture

### Core Components

**Config** - Environment configuration manager
- Loads API keys and Google Sheet credentials
- Validates required environment variables

**SheetsManager** - Google Sheets integration
- Reads leads from source worksheet
- Tracks processed lead IDs
- Writes personalized messages to output worksheet

**ReviewFetcher** - Apify API client
- Fetches Google Maps reviews for place IDs
- Batches review data by business

**AIAgentManager** - AI orchestration
- Manages two specialized AI agents
- Review summarization agent
- Message personalization agent

**LeadProcessor** - Main workflow orchestration
- Coordinates all components
- Enriches leads with review summaries
- Generates personalized messages
- Handles batch processing

### Data Models

All data structures use Pydantic for validation:

- **Lead** - Business and contact information
- **Review** - Individual review data
- **ReviewSummary** - AI-generated owner name and summary
- **PersonalizedMessage** - Generated WhatsApp opener
- **LeadPersonalization** - Final output record

### Workflow

```
Read Leads from Sheet
    ↓
Filter Unprocessed Leads
    ↓
For Each Lead:
    ↓
    Fetch Reviews (Apify)
    ↓
    Summarize Reviews (AI)
    ↓
    Generate Personalized Message (AI)
    ↓
    Write to Output Sheet
```

## Environment Setup

### Environment Variables

Create a `.env` file with:

```env
GOOGLE_SHEET_ID=your_sheet_id
GOOGLE_SHEET_NAME=test_sheets
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=openai/gpt-4.1-mini
APIFY_TOKEN=your_apify_token
```

### Google Service Account

Place `credentials.json` in the project root with Google Sheets API access.

## Installation and Usage

```bash
uv venv
source .venv/bin/activate
uv sync
python -m src
```

The system processes all unprocessed leads in a single run. It automatically:

- Skips leads already in the output sheet
- Logs progress and errors
- Handles validation failures gracefully

## Dependencies

- `pydantic-ai` - AI agent framework
- `gspread` - Google Sheets API client
- `apify-client` - Apify API client
- `pandas` - Data manipulation
- `python-dotenv` - Environment management

## Tooling

- `uv` - Fast Python package installer
- `mypy` - Static type checking
- `ruff` - Python linter and formatter

## Key Features

- **Idempotent processing** - Tracks processed leads to avoid duplicates
- **Batch processing** - Handles multiple leads in one run
- **Error handling** - Validates data at each step
- **Logging** - Detailed progress and error information
- **Type safety** - Full type hints and Pydantic validation
