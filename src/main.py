import asyncio
import logging
import os
from pathlib import Path

import gspread
from apify_client import ApifyClient
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider


def load_prompt(filename: str) -> str:
    prompts_dir = Path(__file__).parent.parent / "prompts"
    prompt_path = prompts_dir / filename
    return prompt_path.read_text().strip()


class Lead(BaseModel):
    id: str | None = None
    business: str | None = None
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    instagram: str | None = None
    facebook: str | None = None
    linkedin: str | None = None
    address: str | None = None
    owner_name: str | None = None
    review_summary: str | None = None


class LeadPersonalization(BaseModel):
    id: str
    name: str
    owner: str
    dm_opener: str
    call_script: str | None = None
    email_opener: str | None = None
    notes: str | None = None


class PersonalizedMessage(BaseModel):
    dm_opener: str


class ReviewSummary(BaseModel):
    owner_name: str
    review_summary: str


class Review(BaseModel):
    title: str | None = None
    name: str | None = None
    text: str | None = None


class Config:
    def __init__(self) -> None:
        load_dotenv()
        self.logger = logging.getLogger(__name__)

        self.google_sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
        self.google_sheet_name = os.getenv("GOOGLE_SHEET_NAME", "test_sheets")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")
        self.apify_token = os.getenv("APIFY_TOKEN", "")

        self._validate()

    def _validate(self) -> None:
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is not set in environment")

        if not self.google_sheet_id:
            raise ValueError("GOOGLE_SHEET_ID is not set in environment")

        if not self.apify_token:
            raise ValueError("APIFY_TOKEN is not set in environment")

        self.logger.info("Configuration loaded successfully")


class ReviewFetcher:
    def __init__(self, api_token: str, max_reviews: int = 20, language: str = "en") -> None:
        self.client = ApifyClient(api_token)
        self.max_reviews = max_reviews
        self.language = language
        self.logger = logging.getLogger(__name__)

    def fetch_reviews(self, place_ids: list[str]) -> list[list[Review]]:
        if not place_ids:
            raise ValueError("place_ids cannot be empty")

        self.logger.info(f"Fetching reviews for {len(place_ids)} place(s)")

        run_input = {
            "placeIds": place_ids,
            "maxReviews": self.max_reviews,
            "language": self.language,
        }

        run = self.client.actor("compass/google-maps-reviews-scraper").call(run_input=run_input)

        all_reviews = []
        for item in self.client.dataset(run["defaultDatasetId"]).iterate_items():
            review = Review(
                title=item.get("title", ""),
                name=item.get("name", ""),
                text=item.get("text", ""),
            )
            all_reviews.append(review)

        results = []
        for i in range(len(place_ids)):
            start_index = i * self.max_reviews
            end_index = start_index + self.max_reviews
            place_reviews = all_reviews[start_index:end_index]
            results.append(place_reviews)
            self.logger.info(f"Fetched {len(place_reviews)} reviews for place ID {place_ids[i]}")

        return results


class SheetsManager:
    def __init__(self, sheet_id: str, sheet_name: str, credentials_file: str = "credentials.json") -> None:
        self.sheet_id = sheet_id
        self.sheet_name = sheet_name
        self.logger = logging.getLogger(__name__)

        if not Path(credentials_file).is_absolute():
            credentials_file = str(Path(__file__).parent.parent / credentials_file)

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(credentials_file, scopes=scopes)
        self.client = gspread.authorize(creds)

        self.logger.info(f"Google Sheets client initialized for sheet: {sheet_name}")

    def read_leads(self) -> list[Lead]:
        self.logger.info(f"Reading leads from sheet: {self.sheet_name}")

        spreadsheet = self.client.open_by_key(self.sheet_id)
        worksheet = spreadsheet.worksheet(self.sheet_name)
        all_values = worksheet.get_all_values()

        if not all_values:
            self.logger.warning("No data found in sheet")
            return []

        headers = all_values[0]
        data_rows = all_values[1:]

        leads = []
        for row in data_rows:
            row_dict = {
                headers[i].lower(): row[i] if i < len(row) else ""
                for i in range(len(headers))
            }
            row_dict = {k: v if v else None for k, v in row_dict.items()}
            leads.append(Lead(**row_dict))

        self.logger.info(f"Successfully read {len(leads)} leads from sheet")
        return leads

    def write_personalization(self, personalization: LeadPersonalization) -> None:
        self.logger.info(f"Writing personalization for lead ID: {personalization.id}")

        spreadsheet = self.client.open_by_key(self.sheet_id)
        worksheet = spreadsheet.worksheet("outreach_personalisation")

        all_values = worksheet.get_all_values()

        if not all_values:
            headers = [
                "ID",
                "Name",
                "Owner",
                "DM opener",
                "Call Script",
                "Email Opener",
                "Notes",
            ]
            worksheet.append_row(headers)
            all_values = [headers]
            self.logger.info("Created headers in outreach_personalisation sheet")

        headers = all_values[0]
        id_col = next((i for i, h in enumerate(headers) if h.lower() == "id"), 0)

        existing_row = None
        for idx, row in enumerate(all_values[1:], start=2):
            if row and len(row) > id_col and row[id_col] == personalization.id:
                existing_row = idx
                break

        row_data = [
            personalization.id,
            personalization.name,
            personalization.owner,
            personalization.dm_opener,
            personalization.call_script or "",
            personalization.email_opener or "",
            personalization.notes or "",
        ]

        if existing_row:
            for col_idx, value in enumerate(row_data, start=1):
                worksheet.update_cell(existing_row, col_idx, value)
            self.logger.info(f"Updated existing row {existing_row} for lead ID: {personalization.id}")
        else:
            worksheet.append_row(row_data)
            self.logger.info(f"Appended new row for lead ID: {personalization.id}")


class AIAgentManager:
    def __init__(self, api_key: str, model_name: str) -> None:
        self.logger = logging.getLogger(__name__)

        model = OpenAIChatModel(
            model_name,
            provider=OpenRouterProvider(api_key=api_key),
        )

        personalization_prompt = load_prompt("dm.md")
        review_summary_prompt = load_prompt("review_summary.md")

        self.personalization_agent: Agent[None, PersonalizedMessage] = Agent(
            model,
            output_type=PersonalizedMessage,
            system_prompt=personalization_prompt,
        )

        self.review_agent: Agent[None, ReviewSummary] = Agent(
            model,
            output_type=ReviewSummary,
            system_prompt=review_summary_prompt,
        )

        self.logger.info("AI agents initialized successfully")

    async def summarize_reviews(self, reviews: list[Review], business_name: str) -> ReviewSummary:
        self.logger.info(f"Summarizing {len(reviews)} reviews for {business_name}")

        first_five = reviews[:5]

        review_texts = []
        for i, review in enumerate(first_five):
            review_text = review.text or ""
            if review_text:
                review_texts.append(f"Review {i + 1}: {review_text}")

        if not review_texts:
            self.logger.warning(f"No review text found for {business_name}")
            return ReviewSummary(owner_name="Unknown", review_summary="No reviews available")

        review_text = "\n\n".join(review_texts)
        prompt = f"Business: {business_name}\n\nReviews:\n{review_text}"

        result = await self.review_agent.run(prompt)
        self.logger.info(f"Review summary generated for {business_name}")
        return result.output

    async def generate_personalized_message(self, lead: Lead) -> PersonalizedMessage:
        self.logger.info(f"Generating personalized message for {lead.business or 'Unknown'}")

        lead_info = f"""
Lead Information:
- Business Name: {lead.business or "Unknown"}
- Owner Name: {lead.owner_name or "Unknown"}
- Review Summary: {lead.review_summary or "No reviews available"}
"""

        result = await self.personalization_agent.run(
            f"Generate a personalized WhatsApp opener for this lead.\n{lead_info}"
        )

        self.logger.info(f"Personalized message generated for {lead.business or 'Unknown'}")
        return result.output


class LeadProcessor:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.logger = logging.getLogger(__name__)

        self.sheets_manager = SheetsManager(
            sheet_id=config.google_sheet_id,
            sheet_name=config.google_sheet_name,
        )

        self.review_fetcher = ReviewFetcher(
            api_token=config.apify_token,
            max_reviews=20,
        )

        self.ai_manager = AIAgentManager(
            api_key=config.openrouter_api_key,
            model_name=config.openrouter_model,
        )

        self.logger.info("LeadProcessor initialized with all components")

    async def enrich_lead_with_reviews(self, lead: Lead) -> Lead:
        if not lead.id:
            self.logger.warning(f"Lead {lead.business or 'Unknown'} has no ID, skipping review fetch")
            return lead

        self.logger.info(f"Enriching lead: {lead.business or 'Unknown'} (ID: {lead.id})")

        reviews_list = self.review_fetcher.fetch_reviews([lead.id])
        reviews = reviews_list[0] if reviews_list else []

        if not reviews:
            self.logger.warning(f"No reviews found for {lead.business or 'Unknown'}")
            return lead

        summary = await self.ai_manager.summarize_reviews(reviews, lead.business or "")

        enriched_lead = lead.model_copy(
            update={
                "owner_name": summary.owner_name,
                "review_summary": summary.review_summary,
            }
        )

        self.logger.info(f"Lead enriched successfully: {lead.business or 'Unknown'}")
        return enriched_lead

    async def process_lead(self, lead: Lead) -> None:
        business_name = lead.business or "Unknown"
        self.logger.info(f"Starting to process lead: {business_name}")

        enriched_lead = await self.enrich_lead_with_reviews(lead)

        personalized_message = await self.ai_manager.generate_personalized_message(enriched_lead)

        self.logger.info(f"Generated DM opener: {personalized_message.dm_opener}")

        lead_id = enriched_lead.id or ""
        if lead_id:
            personalization = LeadPersonalization(
                id=lead_id,
                name=business_name,
                owner=enriched_lead.owner_name or "",
                dm_opener=personalized_message.dm_opener,
            )
            self.sheets_manager.write_personalization(personalization)
            self.logger.info(f"Successfully wrote personalization to sheet for {business_name}")
        else:
            self.logger.warning(f"Lead {business_name} has no ID, skipping sheet write")

    async def process_multiple_leads(self, max_leads: int = 5) -> None:
        self.logger.info("Starting lead processing workflow")

        leads = self.sheets_manager.read_leads()

        if not leads:
            self.logger.error("No leads found in Google Sheets")
            raise ValueError("No leads found in Google Sheets")

        self.logger.info(f"Processing up to {max_leads} leads out of {len(leads)} total")

        for lead in leads[:max_leads]:
            await self.process_lead(lead)

        self.logger.info("Lead processing workflow completed")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    logging.getLogger("apify_client").setLevel(logging.WARNING)
    logging.getLogger("apify").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)

    try:
        logger.info("Starting lead personalization application")

        config = Config()
        processor = LeadProcessor(config)

        asyncio.run(processor.process_multiple_leads(max_leads=5))

        logger.info("Application completed successfully")

    except Exception as e:
        logger.exception(f"Application failed with error: {e}")
        raise


if __name__ == "__main__":
    main()
