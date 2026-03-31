"""
Real AI Voice Processing Service for Agricultural Events
========================================================

This service uses OpenAI's GPT models to intelligently parse voice inputs
and extract structured agricultural event data with high accuracy.
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List

from django.conf import settings

logger = logging.getLogger(__name__)

# Try to import OpenAI
try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:
    OpenAI = None
    AsyncOpenAI = None
    logger.warning("OpenAI library not available")

# Initialize global OpenAI clients
openai_client = None
async_openai_client = None
try:
    OPENAI_AVAILABLE = getattr(settings, "OPENAI_AVAILABLE", False)
    if OPENAI_AVAILABLE and hasattr(settings, "OPENAI_API_KEY") and settings.OPENAI_API_KEY:
        openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        async_openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info("OpenAI clients initialized successfully")
    else:
        logger.warning("OpenAI clients not available - missing API key or library")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI clients: {e}")
    openai_client = None
    async_openai_client = None


class AIVoiceProcessor:
    """
    AI-powered voice processing for agricultural events using OpenAI GPT models.

    This replaces the mock pattern matching with real AI that understands
    natural language and can extract complex agricultural event information.
    """

    def __init__(self):
        self.api_key = getattr(settings, "OPENAI_API_KEY", "")
        self.model = getattr(settings, "OPENAI_MODEL", "gpt-4")
        self.max_tokens = getattr(settings, "OPENAI_MAX_TOKENS", 500)
        self.temperature = getattr(settings, "OPENAI_TEMPERATURE", 0.3)

        if not OPENAI_AVAILABLE:
            logger.warning("OpenAI library not installed. Voice processing will use fallback methods.")
            return

        if not self.api_key:
            logger.warning("OpenAI API key not configured. Voice processing will use fallback methods.")
            return

        # Initialize OpenAI client
        self.openai = OpenAI(api_key=self.api_key)

    def process_voice_input(self, transcript: str, crop_type: str, language: str = "en-US") -> Dict[str, Any]:
        """
        Process voice input using AI to extract structured agricultural event data.

        Args:
            transcript: The voice transcript to process
            crop_type: The crop type context (e.g., "strawberries", "corn")
            language: Language code (e.g., 'en-US', 'es-ES', 'pt-BR')

        Returns:
            Structured event data with confidence scores and extracted information
        """
        start_time = time.time()

        try:
            if not OPENAI_AVAILABLE or not self.api_key:
                return self._fallback_processing(transcript, crop_type, language)

            # Pre-process transcript to fix common speech-to-text errors
            processed_transcript = self._preprocess_transcript(transcript)

            # Create AI prompt for agricultural event extraction
            prompt = self._create_extraction_prompt(processed_transcript, crop_type, language)

            # Call OpenAI API
            response = self.openai.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt(language)},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )

            # Parse AI response
            ai_response = json.loads(response.choices[0].message.content)
            processing_time = (time.time() - start_time) * 1000

            # Structure the response
            result = self._structure_ai_response(ai_response, transcript, processing_time)

            logger.info(
                f"AI voice processing completed in {processing_time:.0f}ms with {result['confidence']}% confidence"
            )
            return result

        except Exception as e:
            logger.error(f"AI voice processing failed: {e}")
            return self._fallback_processing(transcript, crop_type, language)

    def _preprocess_transcript(self, transcript: str) -> str:
        """Pre-process transcript to fix common speech-to-text errors for agricultural terms."""
        import re

        processed = transcript

        # Fix NPK patterns where speech recognition merges numbers
        # "NPK 1010" or "NPK1010" → "NPK 10-10-10"
        processed = re.sub(r"\bNPK\s*(\d{2})(\d{2})(\d{2})\b", r"NPK \1-\2-\3", processed, flags=re.IGNORECASE)
        # "NPK 101010" → "NPK 10-10-10"
        processed = re.sub(r"\bNPK\s*(\d{1,2})(\d{1,2})(\d{1,2})\b", r"NPK \1-\2-\3", processed, flags=re.IGNORECASE)
        # "ten ten ten" or "10 10 10" after NPK → "10-10-10"
        processed = re.sub(
            r"\bNPK\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\b", r"NPK \1-\2-\3", processed, flags=re.IGNORECASE
        )
        # "dash" spoken literally: "10 dash 10 dash 10" → "10-10-10"
        processed = re.sub(r"(\d+)\s*dash\s*(\d+)\s*dash\s*(\d+)", r"\1-\2-\3", processed, flags=re.IGNORECASE)

        return processed

    def _get_system_prompt(self, language: str) -> str:
        """Get the system prompt for the AI model based on language."""

        prompts = {
            "en-US": """You are an expert agricultural assistant for a farm transparency platform.
Your job is to parse voice inputs from farmers and extract structured information about farm activities
to help them document their farming practices transparently.

You must respond with valid JSON containing these fields:
- event_type: One of [fertilization, irrigation, pesticide, herbicide, fungicide, harvest, planting, pruning, transplanting, cultivation, thinning, soil_management, general]. Use "cultivation" for tractor/equipment usage, field operations, or machinery work.
- confidence: Integer 0-100 representing your confidence in the classification
- detected_amounts: Array of structured amounts (e.g., [{"value": 200, "unit": "lbs", "category": "weight"}, {"value": 2, "unit": "hours", "category": "time"}])
- detected_products: Array of products mentioned (e.g., ["NPK 10-10-10", "glyphosate", "diesel"])
- detected_systems: Array of systems/methods (e.g., ["drip irrigation", "broadcast", "tractor"])
- npk_ratio: If fertilizer event and NPK mentioned, extract as "N-P-K" format (e.g., "10-10-10"). null if not mentioned.
- concentration: Chemical concentration if mentioned (e.g., "10-10-10" for NPK, "50%" for liquid). null if not mentioned.
- commercial_name: Product or brand name if mentioned. null if not mentioned.
- application_method: Method of application if mentioned (broadcast, banded, foliar, drip, spray, etc.). null if not mentioned.
- area_covered: Area with unit if mentioned (e.g., {"value": 2, "unit": "hectares"}). null if not mentioned.
- duration: Time duration if mentioned (e.g., {"value": 6, "unit": "hours"}). null if not mentioned.
- fuel_amount: Fuel consumption if mentioned (e.g., {"value": 15, "unit": "gallons"}). null if not mentioned.
- water_source: If irrigation, water source if mentioned. null if not mentioned.
- description: Clean, professional description of the activity

CRITICAL INSTRUCTIONS:
- For NPK ratios: "ten ten ten" means "10-10-10". Always format as N-P-K with hyphens.
- For amounts: Always separate value and unit. "200 pounds per acre" -> value:200, unit:"lbs"
- Prefer specific event types: use "herbicide" when weed-related, "fungicide" when disease/mold-related, "pruning" when trimming/cutting branches.
- IMPORTANT: Products like Kocide, copper hydroxide, copper fungicide, sulfur, mancozeb, or any product targeting disease (anthracnose, blight, mildew, rust, phytophthora) MUST be classified as "fungicide", NOT "fertilization". Fungicides do NOT have NPK values — set npk_ratio to null for fungicide events.
- Only set npk_ratio for fertilization events where NPK is explicitly mentioned.
- If unsure about a value, set it to null rather than guess.
- Focus on extracting actionable farming data for transparency documentation.""",
            "es-ES": """Eres un asistente agrícola experto para una plataforma de transparencia agrícola.
Tu trabajo es analizar entradas de voz de agricultores y extraer información estructurada sobre actividades agrícolas
para ayudarlos a documentar sus prácticas agrícolas de forma transparente.

Debes responder con JSON válido conteniendo estos campos:
- event_type: Uno de [fertilization, irrigation, pesticide, herbicide, fungicide, harvest, planting, pruning, transplanting, cultivation, thinning, soil_management, general]. Usar "cultivation" para uso de tractor/equipo, operaciones de campo, o trabajo con maquinaria.
- confidence: Entero 0-100 representando tu confianza en la clasificación
- detected_amounts: Array de cantidades estructuradas (e.g., [{"value": 200, "unit": "lbs", "category": "weight"}])
- detected_products: Array de productos mencionados
- detected_systems: Array de sistemas/métodos
- npk_ratio: Si es evento de fertilizante y se menciona NPK, extraer como "N-P-K" (e.g., "10-10-10"). null si no se menciona.
- concentration: Concentración química si se menciona. null si no se menciona.
- commercial_name: Nombre del producto o marca si se menciona. null si no se menciona.
- application_method: Método de aplicación si se menciona. null si no se menciona.
- area_covered: Área con unidad si se menciona (e.g., {"value": 2, "unit": "hectáreas"}). null si no se menciona.
- duration: Duración si se menciona (e.g., {"value": 6, "unit": "horas"}). null si no se menciona.
- fuel_amount: Consumo de combustible si se menciona. null si no se menciona.
- water_source: Si es irrigación, fuente de agua si se menciona. null si no se menciona.
- description: Descripción limpia y profesional de la actividad

INSTRUCCIONES CRÍTICAS:
- Para NPK: "diez diez diez" significa "10-10-10". Siempre formatear como N-P-K con guiones.
- Para cantidades: Siempre separar valor y unidad.
- Preferir tipos específicos: usar "herbicide" para malezas, "fungicide" para enfermedades, "pruning" para poda.
- Si no estás seguro de un valor, establecerlo como null en vez de adivinar.""",
            "pt-BR": """Você é um assistente agrícola especialista para uma plataforma de transparência agrícola.
Seu trabalho é analisar entradas de voz de agricultores e extrair informações estruturadas sobre atividades agrícolas
para ajudá-los a documentar suas práticas agrícolas de forma transparente.

Você deve responder com JSON válido contendo estes campos:
- event_type: Um de [fertilization, irrigation, pesticide, herbicide, fungicide, harvest, planting, pruning, transplanting, cultivation, thinning, soil_management, general]. Usar "cultivation" para uso de trator/equipamento, operações de campo, ou trabalho com maquinaria.
- confidence: Inteiro 0-100 representando sua confiança na classificação
- detected_amounts: Array de quantidades estruturadas (e.g., [{"value": 200, "unit": "lbs", "category": "weight"}])
- detected_products: Array de produtos mencionados
- detected_systems: Array de sistemas/métodos
- npk_ratio: Se evento de fertilizante e NPK mencionado, extrair como "N-P-K" (e.g., "10-10-10"). null se não mencionado.
- concentration: Concentração química se mencionada. null se não mencionada.
- commercial_name: Nome do produto ou marca se mencionado. null se não mencionado.
- application_method: Método de aplicação se mencionado. null se não mencionado.
- area_covered: Área com unidade se mencionada (e.g., {"value": 2, "unit": "hectares"}). null se não mencionada.
- duration: Duração se mencionada (e.g., {"value": 6, "unit": "horas"}). null se não mencionada.
- fuel_amount: Consumo de combustível se mencionado. null se não mencionado.
- water_source: Se irrigação, fonte de água se mencionada. null se não mencionada.
- description: Descrição limpa e profissional da atividade

INSTRUÇÕES CRÍTICAS:
- Para NPK: "dez dez dez" significa "10-10-10". Sempre formatar como N-P-K com hifens.
- Para quantidades: Sempre separar valor e unidade.
- Preferir tipos específicos: usar "herbicide" para ervas daninhas, "fungicide" para doenças, "pruning" para poda.
- Se não tem certeza de um valor, definir como null em vez de adivinhar.""",
        }

        return prompts.get(language, prompts["en-US"])

    def _create_extraction_prompt(self, transcript: str, crop_type: str, language: str) -> str:
        """Create the extraction prompt for the AI model."""

        ag_hints = """
AGRICULTURAL PATTERN RECOGNITION HINTS:
- NPK ratios are commonly spoken as "ten ten ten" meaning "10-10-10" (Nitrogen-Phosphorus-Potassium)
- Common fertilizers: Urea (46-0-0), DAP (18-46-0), Triple Super (0-46-0), Potash (0-0-60), MAP (11-52-0)
- Units: "per acre", "per hectare", "pounds", "kilograms", "gallons", "liters"
- Methods: broadcast, banded, foliar, drip, sprinkler, flood, ground spray, aerial

Extract ALL mentioned quantities with their units. Be especially careful with:
1. NPK ratios - always format as N-P-K (e.g., "10-10-10")
2. Amounts with units - separate value from unit
3. Product names - preserve the commercial name exactly as spoken"""

        prompts = {
            "en-US": f"""Parse this farmer's voice input and extract agricultural event information:

Voice Input: "{transcript}"
Crop Type: {crop_type}
Date: Today
{ag_hints}

Respond with JSON only.""",
            "es-ES": f"""Analiza esta entrada de voz del agricultor y extrae información del evento agrícola:

Entrada de Voz: "{transcript}"
Tipo de Cultivo: {crop_type}
Fecha: Hoy
{ag_hints}

Responde solo con JSON.""",
            "pt-BR": f"""Analise esta entrada de voz do agricultor e extraia informações do evento agrícola:

Entrada de Voz: "{transcript}"
Tipo de Cultura: {crop_type}
Data: Hoje
{ag_hints}

Responda apenas com JSON.""",
        }

        return prompts.get(language, prompts["en-US"])

    def _structure_ai_response(
        self, ai_response: Dict[str, Any], original_transcript: str, processing_time: float
    ) -> Dict[str, Any]:
        """Structure the AI response into the expected format."""

        return {
            "type": ai_response.get("event_type", "general"),
            "description": ai_response.get("description", original_transcript),
            "date": time.strftime("%Y-%m-%d"),
            "detected_amounts": ai_response.get("detected_amounts", []),
            "detected_products": ai_response.get("detected_products", []),
            "detected_systems": ai_response.get("detected_systems", []),
            "confidence": min(max(ai_response.get("confidence", 0), 0), 100),
            # Structured fields for direct form mapping
            "npk_ratio": ai_response.get("npk_ratio"),
            "concentration": ai_response.get("concentration"),
            "commercial_name": ai_response.get("commercial_name"),
            "application_method": ai_response.get("application_method"),
            "water_source": ai_response.get("water_source"),
            "area_covered": ai_response.get("area_covered"),
            "duration": ai_response.get("duration"),
            "fuel_amount": ai_response.get("fuel_amount"),
            # Metadata
            "processing_time": processing_time,
            "source": "openai_gpt",
            "model_used": self.model,
            "original_transcript": original_transcript,
        }

    def _fallback_processing(self, transcript: str, crop_type: str, language: str) -> Dict[str, Any]:
        """
        Fallback processing when AI is not available.
        Uses improved pattern matching as backup.
        """
        logger.info("Using fallback pattern matching for voice processing")

        # Pre-process transcript
        processed = self._preprocess_transcript(transcript)

        # Enhanced pattern matching
        patterns = {
            "fertilization": {
                "keywords": [
                    "fertilizer",
                    "fertilize",
                    "npk",
                    "nitrogen",
                    "phosphorus",
                    "potassium",
                    "urea",
                    "compost",
                    "manure",
                ],
                "es": ["fertilizante", "fertilizar", "npk", "nitrógeno", "urea", "compost", "estiércol"],
                "pt": ["fertilizante", "fertilizar", "npk", "nitrogênio", "ureia", "composto", "esterco"],
            },
            "irrigation": {
                "keywords": ["irrigate", "irrigation", "water", "watered", "sprinkler", "drip", "flood"],
                "es": ["irrigar", "irrigación", "regar", "agua", "aspersores", "goteo"],
                "pt": ["irrigar", "irrigação", "regar", "água", "aspersores", "gotejamento"],
            },
            "herbicide": {
                "keywords": ["herbicide", "weed", "weeds", "weed control"],
                "es": ["herbicida", "maleza", "malezas"],
                "pt": ["herbicida", "erva daninha", "ervas daninhas"],
            },
            "fungicide": {
                "keywords": [
                    "fungicide",
                    "fungus",
                    "mildew",
                    "blight",
                    "rot",
                    "mold",
                    "copper",
                    "anthracnose",
                    "kocide",
                    "mancozeb",
                    "sulfur fungicide",
                    "phytophthora",
                ],
                "es": ["fungicida", "hongo", "mildiú", "tizón", "moho", "cobre", "antracnosis"],
                "pt": ["fungicida", "fungo", "míldio", "ferrugem", "mofo", "cobre", "antracnose"],
            },
            "pesticide": {
                "keywords": ["spray", "sprayed", "pesticide", "insecticide", "pest"],
                "es": ["rociar", "pesticida", "insecticida", "plaga"],
                "pt": ["pulverizar", "pesticida", "inseticida", "praga"],
            },
            "pruning": {
                "keywords": ["prune", "pruning", "trim", "trimming", "cut branches"],
                "es": ["podar", "poda", "recortar"],
                "pt": ["podar", "poda", "aparar"],
            },
            "equipment": {
                "keywords": ["tractor", "equipment", "machine", "fuel", "diesel", "mowed", "plowed"],
                "es": ["tractor", "equipo", "máquina", "combustible", "diésel", "cortado", "arado"],
                "pt": ["trator", "equipamento", "máquina", "combustível", "diesel", "cortado", "arado"],
            },
            "harvest": {
                "keywords": ["harvest", "harvested", "picked", "collected", "yield"],
                "es": ["cosechar", "cosechado", "recoger", "recolectar", "rendimiento"],
                "pt": ["colher", "colhido", "colher", "coletar", "rendimento"],
            },
        }

        text_lower = processed.lower()
        detected_type = "general"
        confidence = 30  # Lower confidence for fallback

        # Detect event type
        lang_suffix = "es" if language == "es-ES" else "pt" if language == "pt-BR" else "keywords"

        max_matches = 0
        for event_type, pattern_data in patterns.items():
            keywords = pattern_data.get(lang_suffix, pattern_data["keywords"])
            matches = sum(1 for keyword in keywords if keyword in text_lower)
            if matches > max_matches:
                max_matches = matches
                detected_type = event_type
                confidence = min(30 + matches * 15, 75)  # Max 75% for fallback

        # Extract amounts using regex
        import re

        amount_patterns = [
            (r"(\d+(?:\.\d+)?)\s*(?:pounds?|lbs?)", "lbs", "weight"),
            (r"(\d+(?:\.\d+)?)\s*(?:kg|kilograms?|quilos?|libras?)", "kg", "weight"),
            (r"(\d+(?:\.\d+)?)\s*(?:tons?)", "tons", "weight"),
            (r"(\d+(?:\.\d+)?)\s*(?:gallons?)", "gal", "volume"),
            (r"(\d+(?:\.\d+)?)\s*(?:liters?|litros?)", "L", "volume"),
            (r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|horas?)", "hours", "time"),
            (r"(\d+(?:\.\d+)?)\s*(?:acres?)", "acres", "area"),
            (r"(\d+(?:\.\d+)?)\s*(?:hectares?|hectáreas?)", "ha", "area"),
        ]

        detected_amounts = []
        for pattern, unit, category in amount_patterns:
            matches = re.findall(pattern, processed, re.IGNORECASE)
            for match in matches:
                detected_amounts.append({"value": float(match), "unit": unit, "category": category})

        # Extract NPK ratio
        npk_ratio = None
        npk_match = re.search(r"(\d{1,2})-(\d{1,2})-(\d{1,2})", processed)
        if npk_match:
            npk_ratio = f"{npk_match.group(1)}-{npk_match.group(2)}-{npk_match.group(3)}"

        return {
            "type": detected_type,
            "description": processed,
            "date": time.strftime("%Y-%m-%d"),
            "detected_amounts": detected_amounts,
            "detected_products": [],
            "detected_systems": [],
            "confidence": confidence,
            "npk_ratio": npk_ratio,
            "concentration": npk_ratio,
            "commercial_name": None,
            "application_method": None,
            "water_source": None,
            "area_covered": None,
            "duration": None,
            "fuel_amount": None,
            "processing_time": 50,
            "source": "pattern_matching_fallback",
            "original_transcript": transcript,
        }


def process_voice_with_ai(transcript: str, crop_type: str, language: str = "en-US") -> Dict[str, Any]:
    """
    Synchronous wrapper for async AI processing
    """
    import asyncio

    try:
        # Run the async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(AIVoiceProcessor().process_voice_input_async(transcript, crop_type, language))
        loop.close()
        return result
    except Exception as e:
        logger.error(f"Error in async voice processing: {e}")
        # Fallback to synchronous processing
        processor = AIVoiceProcessor()
        return processor.process_voice_input(transcript, crop_type, language)


async def _fetch_recent_events_from_db(establishment_id: str, parcel_id: str) -> list:
    """
    Fetch recent events from the database for AI context.
    Returns a list of recent event descriptions for the last 30 days.
    """
    from datetime import timedelta

    from django.utils import timezone

    from asgiref.sync import sync_to_async

    from history.models import History

    try:
        # Calculate 30 days ago
        thirty_days_ago = timezone.now() - timedelta(days=30)

        # Query active histories for this parcel (not filtered by start_date,
        # since established productions may have started months ago but still
        # have recent events we need for AI context)
        @sync_to_async
        def get_recent_histories():
            return list(
                History.objects.filter(
                    parcel_id=parcel_id,
                    parcel__establishment_id=establishment_id,
                    finish_date__isnull=True,  # Active (not finished) productions
                ).prefetch_related(
                    "history_weatherevent_events",
                    "history_chemicalevent_events",
                    "history_productionevent_events",
                    "history_generalevent_events",
                    "history_equipmentevent_events",
                    "history_soilmanagementevent_events",
                    "history_pestmanagementevent_events",
                )
            )

        histories = await get_recent_histories()
        recent_events = []
        all_events = []

        for history in histories:

            # Weather events
            for event in history.history_weatherevent_events.all():
                event_type = "weather"
                if hasattr(event, "type"):
                    event_type = f"weather:{event.type}"
                all_events.append((event.date, event_type, getattr(event, "observation", "")))

            # Chemical events
            for event in history.history_chemicalevent_events.all():
                event_type = "chemical"
                if hasattr(event, "commercial_name") and event.commercial_name:
                    event_type = f"chemical:{event.commercial_name}"
                elif hasattr(event, "type"):
                    event_type = f"chemical:{event.type}"
                all_events.append((event.date, event_type, getattr(event, "observation", "")))

            # Production events
            for event in history.history_productionevent_events.all():
                event_type = "production"
                if hasattr(event, "type"):
                    if event.type == "IR":
                        event_type = "irrigation"
                    elif event.type == "HA":
                        event_type = "harvest"
                    elif event.type == "PR":
                        event_type = "pruning"
                    else:
                        event_type = f"production:{event.type}"
                all_events.append((event.date, event_type, getattr(event, "observation", "")))

            # Equipment events
            for event in history.history_equipmentevent_events.all():
                event_type = "equipment"
                if hasattr(event, "equipment_name") and event.equipment_name:
                    event_type = f"equipment:{event.equipment_name}"
                all_events.append((event.date, event_type, getattr(event, "observation", "")))

            # General events
            for event in history.history_generalevent_events.all():
                event_type = "general"
                if hasattr(event, "name") and event.name:
                    event_type = f"general:{event.name}"
                all_events.append((event.date, event_type, getattr(event, "observation", "")))

            # Soil management events
            for event in history.history_soilmanagementevent_events.all():
                event_type = "soil_management"
                if hasattr(event, "type"):
                    event_type = f"soil_management:{event.type}"
                all_events.append((event.date, event_type, getattr(event, "observation", "")))

            # Pest management events
            for event in history.history_pestmanagementevent_events.all():
                event_type = "pest_management"
                if hasattr(event, "type"):
                    event_type = f"pest_management:{event.type}"
                all_events.append((event.date, event_type, getattr(event, "observation", "")))

        # Sort all events by date (most recent first) and format for AI
        all_events.sort(key=lambda x: x[0], reverse=True)

        for event_date, event_type, observation in all_events[:10]:  # Limit to 10 most recent
            days_ago = (timezone.now() - event_date).days
            event_description = f"{event_type}:{days_ago}d_ago"
            if observation and len(observation) < 50:  # Add brief observation if available
                event_description += f"({observation[:30]}...)"
            recent_events.append(event_description)

        logger.info(
            f"Fetched {len(recent_events)} recent events for establishment {establishment_id}, parcel {parcel_id}"
        )
        return recent_events

    except Exception as e:
        logger.error(f"Error fetching recent events from database: {e}")
        return []


async def generate_ai_event_suggestions(
    crop_type: str,
    location: str = None,
    season: str = None,
    recent_events: list = None,  # Keep for backward compatibility but will be ignored
    farm_context: dict = None,
) -> dict:
    """
    Generate AI-powered event suggestions for agricultural activities.
    Now fetches recent events directly from the database for better context.
    """
    import json
    from datetime import datetime

    try:
        # Extract establishment and parcel info from farm_context
        establishment_id = farm_context.get("establishment_id") if farm_context else None
        parcel_id = farm_context.get("parcel_id") if farm_context else None

        # Check if OpenAI is available
        if not async_openai_client:
            logger.warning("OpenAI client not available, using fallback suggestions")
            return _generate_fallback_suggestions(crop_type, season, location)

        # 🆕 Fetch recent events directly from database
        recent_events_context = []
        if establishment_id and parcel_id:
            recent_events_context = await _fetch_recent_events_from_db(establishment_id, parcel_id)

        # Determine season if not provided
        if not season:
            season = _get_season_from_month(datetime.now().month)

        # Build context information for AI
        context_info = f"Crop Type: {crop_type}\nSeason: {season.title()}"

        if location:
            context_info += f"\nLocation: {location}"

        if recent_events_context:
            context_info += f"\nRecent Events (last 30 days): {', '.join(recent_events_context)}"

        if farm_context:
            context_info += f"\nFarm Context: {json.dumps(farm_context, indent=2)}"

        # Create AI prompt for smart suggestions (transparency-first aligned)
        system_prompt = """You are an expert agricultural advisor for a farm transparency platform.
        Generate 3 intelligent, context-aware event suggestions for farmers based on their crop type, season, location, and recent activities.

        CRITICAL RULES:
        - ONLY suggest actual farm operations that a farmer physically performs in the field
        - Each suggestion must be a specific, actionable task with measurable inputs/outputs
        - NEVER suggest workshops, tours, educational events, marketing activities, or meetings
        - NEVER suggest consumer engagement, certifications, or administrative tasks
        - Good examples: "Apply pre-bloom nitrogen fertilizer", "Dormant season pruning", "Drip irrigation system flush"
        - Bad examples: "Nutrient Management Workshop", "Consumer Farm Tour", "Sustainability Certification Review"

        Focus on:
        1. Seasonal timing — what specific crop operation is needed RIGHT NOW for this crop stage
        2. Agronomic accuracy — match real farming calendars for the crop and region
        3. Practical specificity — include rates, methods, equipment, or techniques
        4. Operational variety — suggest different operation types (not all fertilization)

        Category MUST be one of: fertilization, irrigation, pest_control, harvest, cultivation, soil_management, pruning

        Return ONLY a valid JSON object with this exact structure:
        {
            "suggestions": [
                {
                    "id": "unique_id",
                    "name": "Specific Operation Name",
                    "description": "What the farmer physically does, with specifics",
                    "reasoning": "Why this operation is needed now for this crop",
                    "carbon_impact": 25.5,
                    "priority": "high|medium|low",
                    "confidence": 85,
                    "timing_relevance": "Why now is the right time",
                    "efficiency_tips": ["tip1", "tip2"],
                    "estimated_duration": "2-3 hours",
                    "category": "fertilization|irrigation|pest_control|harvest|cultivation|soil_management|pruning",
                    "seasonal_relevance": 90,
                    "best_practices": ["practice1", "practice2"]
                }
            ],
            "reasoning": "Overall reasoning for these suggestions",
            "ai_confidence": 85
        }"""

        # Build recent events instruction
        recent_events_instruction = ""
        if recent_events_context:
            recent_events_instruction = f"""
        IMPORTANT — The farmer has ALREADY completed these recent events:
        {', '.join(recent_events_context)}
        DO NOT suggest operations the farmer has already done recently.
        Suggest COMPLEMENTARY activities they haven't done yet this season."""

        user_prompt = f"""
        Generate 3 specific farm operations for:
        {context_info}

        Current month: {datetime.now().strftime('%B')}
        {recent_events_instruction}

        Consider the typical {crop_type} agronomic calendar for {season} season in this region.
        What specific field operations should a {crop_type} farmer be doing RIGHT NOW?
        Think about: crop stage, pest/disease pressure, nutrient timing, water needs, pruning windows.
        Each suggestion must be a hands-on farm task, not a workshop, tour, or administrative activity.
        """

        # Call OpenAI API
        response = await async_openai_client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.7,  # Allow some creativity while maintaining consistency
            max_tokens=1500,
            timeout=15.0,
        )

        # Parse AI response
        ai_content = response.choices[0].message.content.strip()

        # Clean up the response (remove any markdown formatting)
        if ai_content.startswith("```json"):
            ai_content = ai_content[7:]
        if ai_content.endswith("```"):
            ai_content = ai_content[:-3]

        try:
            ai_suggestions = json.loads(ai_content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse AI suggestions JSON: {e}")
            return _generate_fallback_suggestions(crop_type, season, location)

        # Validate and enhance the AI response
        if not ai_suggestions.get("suggestions"):
            return _generate_fallback_suggestions(crop_type, season, location)

        # Add metadata
        result = {
            **ai_suggestions,
            "context": {
                "season": season,
                "crop_type": crop_type,
                "location": location,
                "current_month": datetime.now().month,
            },
            "generated_at": datetime.now().isoformat(),
            "ai_powered": True,
            "processing_time": 0.8,  # Approximate
        }

        logger.info(f"Generated AI event suggestions for {crop_type} in {season}")
        return result

    except Exception as e:
        logger.error(f"Error generating AI event suggestions: {e}")
        return _generate_fallback_suggestions(crop_type, season, location)


def _generate_fallback_suggestions(crop_type: str, season: str = None, location: str = None) -> dict:
    """
    Generate crop-aware fallback suggestions when AI is unavailable.
    Suggestions are tailored to the specific crop type and current season.
    """
    current_month = datetime.now().month
    season = season or _get_season_from_month(current_month)

    # Crop-aware seasonal suggestions
    crop = crop_type or "crops"
    crop_lower = crop.lower()

    # Determine if crop is a perennial (tree/vine) or annual
    perennial_keywords = [
        "orange",
        "citrus",
        "avocado",
        "apple",
        "grape",
        "vine",
        "tree",
        "mango",
        "peach",
        "cherry",
        "lemon",
        "lime",
        "olive",
        "walnut",
        "almond",
        "pecan",
        "blueberry",
        "coffee",
        "cacao",
    ]
    is_perennial = any(kw in crop_lower for kw in perennial_keywords)

    seasonal_suggestions = {
        "spring": [
            {
                "id": f"spring_nutrition_{crop_type}",
                "name": f"{crop} Spring Nutrition Program",
                "description": f"Apply balanced fertilization to support {crop} spring growth and flowering",
                "reasoning": f"Spring is critical for {crop} nutrient uptake during active growth phase",
                "carbon_impact": 15.0,
                "priority": "high",
                "confidence": 80,
                "timing_relevance": f"Optimal fertilization window for {crop} spring growth",
                "efficiency_tips": [
                    f"Soil test before fertilizing {crop}",
                    "Split applications for better uptake",
                ],
                "estimated_duration": "3-4 hours",
                "category": "fertilization",
                "seasonal_relevance": 95,
                "best_practices": [
                    "Use soil test results to guide application rates",
                    "Apply during cool morning hours",
                ],
            },
            {
                "id": f"spring_pest_scout_{crop_type}",
                "name": f"{crop} Pest Scouting",
                "description": f"Early-season pest and disease monitoring for {crop}",
                "reasoning": f"Spring pest emergence requires early detection for effective {crop} management",
                "carbon_impact": 5.0,
                "priority": "high",
                "confidence": 78,
                "timing_relevance": f"Critical early detection window for {crop} pests",
                "efficiency_tips": [
                    "Scout field edges and hotspots first",
                    "Document pest pressure levels for transparency",
                ],
                "estimated_duration": "1-2 hours",
                "category": "pest_control",
                "seasonal_relevance": 90,
                "best_practices": [
                    "Use IPM thresholds before treating",
                    "Record findings for consumer transparency",
                ],
            },
        ],
        "summer": [
            {
                "id": f"summer_irrigation_{crop_type}",
                "name": f"{crop} Irrigation Management",
                "description": f"Optimize water delivery for {crop} during peak demand",
                "reasoning": f"Summer heat increases {crop} water demand — efficient irrigation is critical",
                "carbon_impact": 20.0,
                "priority": "high",
                "confidence": 85,
                "timing_relevance": f"Peak water demand period for {crop}",
                "efficiency_tips": [
                    "Use soil moisture sensors to avoid over-watering",
                    "Irrigate during cooler hours to reduce evaporation",
                ],
                "estimated_duration": "2-3 hours",
                "category": "irrigation",
                "seasonal_relevance": 95,
                "best_practices": [
                    "Drip irrigation for water efficiency",
                    "Monitor soil moisture at root zone depth",
                ],
            },
            {
                "id": f"summer_pest_monitoring_{crop_type}",
                "name": f"{crop} Integrated Pest Monitoring",
                "description": f"Monitor and manage pest pressure on {crop} using sustainable IPM",
                "reasoning": f"Summer pest pressure on {crop} requires proactive sustainable management",
                "carbon_impact": 12.0,
                "priority": "medium",
                "confidence": 78,
                "timing_relevance": f"Peak pest activity period for {crop}",
                "efficiency_tips": [
                    "Scout weekly and record pest counts",
                    "Use beneficial insects where possible",
                ],
                "estimated_duration": "1-2 hours weekly",
                "category": "pest_control",
                "seasonal_relevance": 85,
                "best_practices": [
                    "Follow IPM protocols",
                    "Document all scouting for transparency records",
                ],
            },
        ],
        "fall": [
            {
                "id": f"fall_harvest_{crop_type}",
                "name": f"{crop} Harvest" if is_perennial else f"{crop} Harvest Operations",
                "description": f"Harvest {crop} with quality monitoring and efficient handling",
                "reasoning": f"{'Fruit maturity assessment and picking' if is_perennial else 'Fall harvest season'} for {crop}",
                "carbon_impact": 35.0,
                "priority": "high",
                "confidence": 90,
                "timing_relevance": f"{'Check Brix and maturity before harvest' if is_perennial else 'Peak harvest window'} for {crop}",
                "efficiency_tips": [
                    "Monitor quality indicators before harvest",
                    "Optimize equipment routes for fuel efficiency",
                ],
                "estimated_duration": "6-12 hours",
                "category": "harvest",
                "seasonal_relevance": 95,
                "best_practices": [
                    "Quality grade assessment at harvest",
                    "Document yield per area for transparency",
                ],
            },
            {
                "id": f"fall_soil_{crop_type}",
                "name": f"Post-{'Harvest' if is_perennial else 'Season'} Soil Care for {crop}",
                "description": f"Soil health maintenance after {crop} growing season",
                "reasoning": f"Fall is ideal for restoring soil health after {crop} production",
                "carbon_impact": -20.0,
                "priority": "medium",
                "confidence": 80,
                "timing_relevance": f"Optimal window for soil recovery after {crop} season",
                "efficiency_tips": [
                    "Soil test to assess nutrient depletion",
                    "Add organic matter or cover crops",
                ],
                "estimated_duration": "3-5 hours",
                "category": "soil_management",
                "seasonal_relevance": 88,
                "best_practices": [
                    "Cover cropping for soil protection",
                    "Document soil health practices for transparency",
                ],
            },
        ],
        "winter": [
            {
                "id": f"winter_maintenance_{crop_type}",
                "name": f"{'Pruning & Training' if is_perennial else 'Equipment Maintenance'} for {crop}",
                "description": (
                    f"Winter pruning and canopy management for {crop} trees"
                    if is_perennial
                    else f"Maintain and prepare equipment for next {crop} season"
                ),
                "reasoning": (
                    f"Dormant season is ideal for {crop} structural pruning"
                    if is_perennial
                    else f"Winter downtime is perfect for equipment maintenance"
                ),
                "carbon_impact": 8.0,
                "priority": "high" if is_perennial else "medium",
                "confidence": 75,
                "timing_relevance": (
                    f"Dormant pruning window for {crop}" if is_perennial else "Ideal maintenance window"
                ),
                "efficiency_tips": (
                    [
                        "Remove dead and crossing branches",
                        "Shape canopy for light penetration",
                    ]
                    if is_perennial
                    else [
                        "Service engines and check fuel systems",
                        "Calibrate application equipment",
                    ]
                ),
                "estimated_duration": "4-8 hours",
                "category": "equipment",
                "seasonal_relevance": 82,
                "best_practices": (
                    [
                        "Sanitize pruning tools between trees",
                        "Document pruning for transparency records",
                    ]
                    if is_perennial
                    else [
                        "Preventive maintenance schedule",
                        "Document equipment condition",
                    ]
                ),
            },
            {
                "id": f"winter_planning_{crop_type}",
                "name": f"{crop} Season Planning & Soil Analysis",
                "description": f"Plan next season's {crop} management and analyze soil data",
                "reasoning": f"Winter is the best time to review {crop} performance and plan improvements",
                "carbon_impact": 0.0,
                "priority": "medium",
                "confidence": 70,
                "timing_relevance": f"Planning window for next {crop} season",
                "efficiency_tips": [
                    "Review last season's yield and input data",
                    "Order inputs early for better pricing",
                ],
                "estimated_duration": "2-4 hours",
                "category": "soil_management",
                "seasonal_relevance": 75,
                "best_practices": [
                    "Use transparency records to identify improvements",
                    "Set goals for next season's documentation",
                ],
            },
        ],
    }

    suggestions = seasonal_suggestions.get(season, seasonal_suggestions["summer"])[:3]

    return {
        "suggestions": suggestions,
        "reasoning": f"Suggested activities for {crop} during {season} season based on typical farming calendar and best practices",
        "context": {"season": season, "crop_type": crop_type, "location": location, "current_month": current_month},
        "ai_confidence": 65,
        "generated_at": datetime.now().isoformat(),
        "ai_powered": False,
        "fallback_mode": True,
    }


def _get_season_from_month(month: int) -> str:
    """Get season from month number."""
    if 3 <= month <= 5:
        return "spring"
    elif 6 <= month <= 8:
        return "summer"
    elif 9 <= month <= 11:
        return "fall"
    else:
        return "winter"
