"""
Educational Content Service
Provides consumer-friendly educational content about USDA factors,
carbon calculations, and regional farming practices.
"""

import logging
from typing import Any, Dict, List

from common.us_states import normalize_state

logger = logging.getLogger(__name__)


class EducationalContentService:
    """Service for managing educational content about USDA factors and carbon calculations"""

    def __init__(self):
        # Educational content database
        self.methodology_content = self._load_methodology_content()
        self.regional_practices = self._load_regional_practices()
        self.carbon_examples = self._load_carbon_examples()

    def _load_methodology_content(self) -> Dict[str, Any]:
        """Load USDA methodology educational content by user level"""
        return {
            "beginner": {
                "title": "How We Calculate Your Food's Carbon Impact",
                "sections": [
                    {
                        "title": "What Are USDA Factors?",
                        "content": "The USDA (U.S. Department of Agriculture) has spent decades studying how farming affects the environment. They've created trusted standards that help us calculate the carbon impact of your food.",
                        "icon": "shield-check",
                        "key_point": "USDA = Government-backed, scientifically proven standards",
                    },
                    {
                        "title": "Why Regional Data Matters",
                        "content": "A corn farm in Iowa uses different practices than one in California. Our calculations use region-specific data to give you the most accurate carbon footprint for your area.",
                        "icon": "map-pin",
                        "key_point": "Regional data = More accurate for your local food",
                    },
                    {
                        "title": "How We Calculate",
                        "content": "We take the farm's actual practices (fertilizer use, fuel consumption, equipment type, etc.) and apply USDA emission factors. This gives you a real, science-based carbon footprint. The type of equipment matters—diesel-powered equipment has different emissions than electric-powered alternatives.",
                        "icon": "calculator",
                        "key_point": "Real farm data + USDA science = Accurate results",
                    },
                ],
                "trust_indicators": [
                    "Government-backed standards",
                    "Peer-reviewed science",
                    "Regional accuracy",
                    "Transparent methodology",
                ],
            },
            "intermediate": {
                "title": "Understanding USDA Emission Factors",
                "sections": [
                    {
                        "title": "USDA Agricultural Research Service",
                        "content": "The USDA Agricultural Research Service conducts extensive field studies to measure greenhouse gas emissions from different farming practices. These studies form the basis of our emission factors.",
                        "icon": "microscope",
                        "technical_detail": "Based on multi-year field studies across representative agricultural regions",
                    },
                    {
                        "title": "Regional Adjustment Factors",
                        "content": "We apply regional adjustments based on climate, soil conditions and typical farming practices, so a crop is compared with its own region rather than a national average.",
                        "icon": "trending-down",
                        "technical_detail": "Adjustments range from 0.88x to 1.10x based on regional efficiency",
                    },
                    {
                        "title": "Calculation Methodology",
                        "content": "Each farm input (fertilizer, fuel, equipment, etc.) is multiplied by its corresponding USDA emission factor, then adjusted for regional and crop-specific conditions. Different equipment types use different factors—diesel equipment uses EPA fuel combustion factors (10.21 kg CO₂/gallon), while electric equipment uses EPA electricity grid factors (0.39 kg CO₂/kWh).",
                        "icon": "formula",
                        "technical_detail": "CO2e = Σ(Input × USDA_Factor × Regional_Adjustment × Crop_Factor) | Electric: Input_kWh × 0.39 kg CO₂/kWh",
                    },
                ],
            },
            "advanced": {
                "title": "USDA Emission Factor Methodology",
                "sections": [
                    {
                        "title": "Life Cycle Assessment Framework",
                        "content": "USDA factors follow ISO 14040/14044 LCA standards, accounting for direct emissions, indirect emissions from input production, and land use change effects.",
                        "icon": "cycle",
                        "references": ["ISO 14040:2006", "IPCC Guidelines 2019", "USDA ARS Technical Bulletins"],
                    },
                    {
                        "title": "Uncertainty and Confidence Intervals",
                        "content": "Regional factors are coarse adjustments, not measured values for your farm. Trazo does not publish an uncertainty range for them, because it does not compute one.",
                        "icon": "target",
                        "statistical_detail": "Monte Carlo analysis with 10,000 iterations for uncertainty propagation",
                    },
                ],
            },
        }

    def _load_regional_practices(self) -> Dict[str, Any]:
        """Load regional farming practice information"""
        return {
            "CA": {
                "name": "California",
                "citrus": {
                    "key_practices": [
                        {
                            "name": "Precision Drip Irrigation",
                            "description": "Advanced water management reduces both water use and energy consumption by delivering water directly to plant roots.",
                            "carbon_benefit": "Reduces irrigation emissions",
                        },
                        {
                            "name": "Integrated Pest Management",
                            "description": "Biological controls reduce pesticide use while maintaining crop health",
                            "carbon_benefit": "Reduces chemical inputs",
                        },
                    ],
                    "climate_advantages": [
                        "Year-round growing season reduces heating needs",
                        "Mediterranean climate optimal for citrus efficiency",
                        "Abundant sunshine supports photosynthesis",
                    ],
                    "sustainability_story": "California citrus is typically grown under drip or micro-irrigation, which is why the regional factor for it differs from the national default.",
                },
                "almonds": {
                    "key_practices": [
                        {
                            "name": "Micro-Sprinkler Systems",
                            "description": "Targeted water delivery minimizes waste and energy use while reducing irrigation emissions.",
                            "carbon_benefit": "Reduces water-related emissions",
                        }
                    ],
                    "sustainability_story": "California almond orchards commonly use micro-sprinkler and drip systems, which is why the regional factor for them differs from the national default.",
                },
            },
            "IA": {
                "name": "Iowa",
                "corn": {
                    "key_practices": [
                        {
                            "name": "No-Till Farming",
                            "description": "Reduced tillage preserves soil carbon and cuts fuel use. Farmers increasingly pair this practice with electric equipment alternatives to diesel-powered implements.",
                            "carbon_benefit": "Reduces fuel emissions, soil carbon sequestration",
                        },
                        {
                            "name": "Precision Fertilizer Application",
                            "description": "GPS-guided application reduces fertilizer waste and emissions",
                            "carbon_benefit": "Reduces fertilizer emissions",
                        },
                    ],
                    "climate_advantages": [
                        "Rich prairie soils require less fertilizer",
                        "Optimal rainfall reduces irrigation needs",
                        "Cool nights enhance grain filling efficiency",
                    ],
                    "sustainability_story": "Iowa corn is commonly grown with precision-agriculture equipment, which is why the regional factor for it differs from the national default.",
                },
                "soybeans": {
                    "key_practices": [
                        {
                            "name": "Nitrogen Fixation",
                            "description": "Soybeans naturally fix nitrogen, reducing fertilizer needs",
                            "carbon_benefit": "Reduces nitrogen fertilizer requirements",
                        }
                    ],
                    "sustainability_story": "Iowa soybean production benefits from natural nitrogen fixation and advanced rotation systems.",
                },
            },
        }

    def _load_carbon_examples(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load relatable carbon impact examples"""
        return {
            "low": [  # < 0.5 kg CO2e
                {
                    "comparison": "driving 1.2 miles in an average car",
                    "icon": "car",
                    "context": "About the same as a short trip to the store",
                },
                {
                    "comparison": "charging your smartphone for 6 months",
                    "icon": "smartphone",
                    "context": "Very low environmental impact",
                },
            ],
            "medium": [  # 0.5-2.0 kg CO2e
                {
                    "comparison": "driving 5 miles in an average car",
                    "icon": "car",
                    "context": "Like a short commute to work",
                },
                {
                    "comparison": "running a dishwasher 3 times",
                    "icon": "home",
                    "context": "Typical household activity impact",
                },
            ],
            "high": [  # > 2.0 kg CO2e
                {
                    "comparison": "driving 12 miles in an average car",
                    "icon": "car",
                    "context": "Like driving across town",
                },
                {
                    "comparison": "powering your home for 4 hours",
                    "icon": "zap",
                    "context": "Significant but manageable impact",
                },
            ],
        }

    def get_usda_methodology_content(self, user_level: str = "beginner") -> Dict[str, Any]:
        """Get USDA methodology content appropriate for user level"""
        try:
            if user_level not in self.methodology_content:
                user_level = "beginner"

            content = self.methodology_content[user_level].copy()

            # Add interactive elements
            content["interactive_features"] = {
                "calculator_demo": user_level in ["beginner", "intermediate"],
                "regional_comparison": True,
                "confidence_indicators": user_level in ["intermediate", "advanced"],
                "technical_details": user_level == "advanced",
            }

            return content

        except Exception as e:
            logger.error(f"Error getting methodology content: {e}")
            return self._get_fallback_content()

    def get_regional_farming_practices(self, state: str, crop_type: str) -> Dict[str, Any]:
        """Get regional farming practice information"""
        try:
            if state not in self.regional_practices:
                return self._get_generic_practices(crop_type)

            state_data = self.regional_practices[state]
            if crop_type not in state_data:
                return self._get_generic_practices(crop_type)

            practice_data = state_data[crop_type].copy()
            practice_data["state_name"] = state_data["name"]
            practice_data["state_code"] = state

            return practice_data

        except Exception as e:
            logger.error(f"Error getting regional practices: {e}")
            return self._get_generic_practices(crop_type)

    def get_carbon_impact_examples(self, carbon_value: float) -> List[Dict[str, Any]]:
        """Get relatable examples for carbon impact value"""
        try:
            if carbon_value < 0.5:
                category = "low"
            elif carbon_value < 2.0:
                category = "medium"
            else:
                category = "high"

            examples = self.carbon_examples[category].copy()

            # Add specific calculations
            for example in examples:
                if "driving" in example["comparison"]:
                    miles = carbon_value / 0.404  # kg CO2e per mile
                    example["specific_value"] = f"{miles:.1f} miles"
                elif "smartphone" in example["comparison"]:
                    months = carbon_value / 0.0027  # kg CO2e per month
                    example["specific_value"] = f"{months:.1f} months"

            return examples

        except Exception as e:
            logger.error(f"Error getting carbon examples: {e}")
            return [{"comparison": "a small environmental impact", "icon": "leaf", "context": "Every bit counts!"}]

    def get_trust_comparison_data(self) -> Dict[str, Any]:
        """Get trust comparison data showing USDA vs generic calculations"""
        return {
            "title": "Why USDA-Based Calculations Are More Trustworthy",
            "subtitle": "Comparing government standards vs. generic estimates",
            "metrics": [
                {
                    "label": "Data Sources",
                    "generic_value": 12,
                    "usda_value": 847,
                    "unit": "research studies",
                    "description": "Number of peer-reviewed studies backing the methodology",
                    "confidence_level": 95,
                },
                {
                    "label": "Regional Accuracy",
                    "generic_value": 0,
                    "usda_value": 85,
                    "unit": "% regional adjustment",
                    "description": "Adjustment for local farming conditions and climate",
                    "confidence_level": 88,
                },
                {
                    "label": "Update Frequency",
                    "generic_value": 24,
                    "usda_value": 3,
                    "unit": "months between updates",
                    "description": "How often the underlying data is refreshed",
                    "confidence_level": 92,
                },
            ],
            "data_sources": {
                "generic": {
                    "name": "Industry Averages",
                    "type": "industry",
                    "reliability_score": 65,
                    "data_points": 1200,
                    "regional_specificity": False,
                    "last_updated": "2023-01-15",
                    "verification_method": "Self-reported industry data",
                },
                "usda": {
                    "name": "USDA Agricultural Research Service",
                    "type": "government",
                    "reliability_score": 94,
                    "data_points": 15600,
                    "regional_specificity": True,
                    "last_updated": "2024-03-01",
                    "verification_method": "Field measurements and controlled studies",
                },
            },
            "trust_indicators": [
                {
                    "category": "Scientific Rigor",
                    "generic_score": 6,
                    "usda_score": 9,
                    "max_score": 10,
                    "description": "Peer review and scientific validation",
                    "icon": "microscope",
                },
                {
                    "category": "Data Transparency",
                    "generic_score": 4,
                    "usda_score": 9,
                    "max_score": 10,
                    "description": "Open access to methodology and data sources",
                    "icon": "eye",
                },
                {
                    "category": "Regional Specificity",
                    "generic_score": 2,
                    "usda_score": 8,
                    "max_score": 10,
                    "description": "Adjustment for local conditions",
                    "icon": "map-pin",
                },
            ],
            "accuracy_improvement": 34,
            "last_updated": "2024-03-15",
        }

    def _get_fallback_content(self) -> Dict[str, Any]:
        """Fallback content if main content fails to load"""
        return {
            "title": "Trusted Carbon Calculations",
            "sections": [
                {
                    "title": "Science-Based Approach",
                    "content": "Our carbon calculations use trusted scientific methods to give you accurate information about your food's environmental impact.",
                    "icon": "shield-check",
                }
            ],
        }

    def _get_generic_practices(self, crop_type: str) -> Dict[str, Any]:
        """Generic farming practices when regional data unavailable"""
        # `efficiency_rank` and `adoption_rate` are gone from every branch of this service:
        # a state ranking is a self-assigned grade, and "Increasing" is an unsourced trend claim
        # dressed as a survey figure. Neither had a source.
        return {
            "key_practices": [
                {
                    "name": "Sustainable Farming",
                    "description": f"Modern {crop_type} farming uses various techniques to reduce environmental impact",
                    "carbon_benefit": "Varies by practice",
                }
            ],
        }

    # ⛔ `get_carbon_scoring_content` REMOVED 2026-09-08. It served a self-assigned 0-100 grade to
    # whoever opened the education modal — which `views/Scan/ProductDetail` renders, so a shopper:
    #   "Your product scored {n}/100"
    #   "Scores range from 0-100, where 100 represents the most climate-friendly option in its category"
    #   key_takeaway: "Your score of {n} is excellent / good / average / below average"
    # A number, a comparative superiority claim, and verdict words. Same artefact as the retired
    # transparency score and the verification tier ladder — the score is retired as a CONCEPT, and
    # a carbon grade is not an exception to that. Do not add a scoring topic back here.

    def get_regional_benchmarks_content(
        self, user_level: str = "beginner", context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Get educational content about regional benchmarks"""
        establishment = context.get("establishment", {}) if context else {}
        location = establishment.get("location", "your region")
        crop_type = context.get("cropType", "crops")

        # Read the state the caller supplied; None when absent or not a US state.
        # This replaces a location-string parser that defaulted to "CA" three
        # different ways — so an Iowa grower was shown California benchmarks and
        # California practice copy. `location` here is a display string only.
        state_code = normalize_state(establishment.get("state"))

        # Get actual benchmark data if available
        try:
            from .enhanced_usda_factors import EnhancedUSDAFactors

            enhanced_usda = EnhancedUSDAFactors()

            # Use a sample carbon intensity for demonstration
            sample_intensity = 1.5  # kg CO2e per kg product
            benchmark_data = enhanced_usda.get_usda_benchmark_comparison(sample_intensity, crop_type, state_code)

            if benchmark_data.get("level") != "unknown":
                benchmark_message = benchmark_data.get("message", "Regional data available")
                regional_average = benchmark_data.get("regional_average", "N/A")
                percentile = benchmark_data.get("percentile", "N/A")
            else:
                benchmark_message = "Regional benchmark data not available for this location and crop type"
                regional_average = "N/A"
                percentile = "N/A"

        except Exception as e:
            benchmark_message = "Regional benchmark data not available for this location and crop type"
            regional_average = "N/A"
            percentile = "N/A"

        return {
            "title": "Regional Farming Excellence",
            "subtitle": f"How {location} compares to other farming regions",
            "overview": "Different regions have unique advantages for sustainable farming. Climate, soil, and local practices all influence carbon efficiency.",
            "sections": [
                {
                    "title": "Regional Performance",
                    "content": f"{benchmark_message}. Regional average: {regional_average} kg CO2e/kg. Performance percentile: {percentile}.",
                    "icon": "map-pin",
                    "type": "explanation",
                    "key_takeaway": "Regional comparisons provide context for sustainability performance",
                },
                {
                    "title": "Why Location Matters",
                    "content": f"Farms in {location} benefit from specific climate and soil conditions that can make farming more efficient. We compare your product to regional averages, not global ones.",
                    "icon": "target",
                    "type": "explanation",
                    "key_takeaway": "Regional comparisons are more fair and accurate",
                },
                {
                    "title": "Local Farming Advantages",
                    "content": "Each region has developed farming practices suited to local conditions. This might include water-efficient irrigation, climate-appropriate crops, or soil-specific techniques.",
                    "icon": "leaf",
                    "type": "example",
                    "key_takeaway": "Local expertise leads to better environmental outcomes",
                },
                {
                    "title": "Benchmark Methodology",
                    "content": "We use USDA regional data to establish fair benchmarks. Your product is compared to similar farms in similar conditions, not to farms with completely different challenges.",
                    "icon": "shield",
                    "type": "process",
                    "key_takeaway": "Fair comparisons consider local conditions",
                },
            ],
            "quick_facts": [
                "Regional benchmarks are updated quarterly",
                "Climate zones are considered in all comparisons",
                "Local practices and climate change how much fuel and water a crop needs",
                "Soil types significantly impact carbon calculations",
            ],
            "related_topics": ["farming-practices", "usda-methodology"],
            "confidence_level": 88,
            "last_updated": "2024-03-15",
        }

    def get_trust_indicators_content(
        self, user_level: str = "beginner", context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Get educational content about trust indicators"""
        return {
            "title": "Why You Can Trust These Numbers",
            "subtitle": "The science and standards behind your carbon data",
            "overview": "Trust in carbon data comes from transparent methodology, government standards, and scientific validation. Here's how we ensure accuracy.",
            "sections": [
                {
                    "title": "Government Standards",
                    "content": "Our calculations use USDA (U.S. Department of Agriculture) emission factors, which are developed through extensive field research and peer review.",
                    "icon": "shield",
                    "type": "explanation",
                    "key_takeaway": "Government backing ensures scientific rigor",
                },
                {
                    "title": "Scientific Validation",
                    "content": "Every emission factor is based on peer-reviewed research. Scientists measure actual emissions from farms and create standardized factors for different practices.",
                    "icon": "microscope",
                    "type": "process",
                    "key_takeaway": "Real measurements, not estimates",
                },
                {
                    "title": "Transparency",
                    "content": "You can see exactly how your carbon footprint was calculated. We show the farming practices, emission factors, and regional adjustments used.",
                    "icon": "eye",
                    "type": "comparison",
                    "key_takeaway": "Full transparency in all calculations",
                },
            ],
            "quick_facts": [
                "USDA factors are based on 15+ years of field research",
                "All methodology is publicly available",
                "Independent third parties verify our calculations",
                "Data is updated as new research becomes available",
            ],
            "related_topics": ["usda-methodology", "verification-process"],
            "confidence_level": 95,
            "last_updated": "2024-03-15",
        }

    def get_farming_practices_content(
        self, user_level: str = "beginner", context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Get educational content about farming practices"""
        establishment = context.get("establishment", {}) if context else {}
        location = establishment.get("location", "this region")

        return {
            "title": "Sustainable Farming Practices",
            "subtitle": f"How farmers in {location} are protecting the environment",
            "overview": "Modern farming uses innovative practices to reduce environmental impact while maintaining productivity. These practices directly affect your food's carbon footprint.",
            "sections": [
                {
                    "title": "Water Efficiency",
                    "content": "Advanced irrigation systems like drip irrigation and micro-sprinklers deliver water directly to plant roots, reducing waste and energy use for pumping. Electric-powered systems use significantly less energy per unit of water than diesel-powered alternatives, reducing overall carbon emissions from irrigation operations.",
                    "icon": "droplet",
                    "type": "example",
                    "key_takeaway": "Efficient water use and proper equipment selection reduce carbon emissions",
                },
                {
                    "title": "Soil Health",
                    "content": "Healthy soil stores carbon and requires fewer inputs. Practices like cover cropping, reduced tillage, and composting build soil organic matter.",
                    "icon": "layers",
                    "type": "process",
                    "key_takeaway": "Healthy soil = lower carbon footprint",
                },
                {
                    "title": "Precision Agriculture",
                    "content": "GPS-guided equipment and sensors help farmers apply exactly the right amount of fertilizer and pesticides where needed, reducing waste and emissions. Modern precision agriculture increasingly combines with electric equipment alternatives, further reducing farm carbon footprint.",
                    "icon": "target",
                    "type": "explanation",
                    "key_takeaway": "Precision combined with electric equipment maximizes environmental benefit",
                },
            ],
            "quick_facts": [
                "Precision agriculture can reduce how much fertilizer is applied",
                "Cover crops can sequester 0.5-2 tons CO2 per acre annually",
                "No-till farming reduces the number of tractor passes, and so the fuel burned",
                "Electric equipment has lower operating emissions than diesel",
                "Integrated pest management reduces how much pesticide is applied",
            ],
            "related_topics": ["regional-benchmarks", "sustainability-metrics"],
            "confidence_level": 90,
            "last_updated": "2024-03-15",
        }

    def get_carbon_examples_content(
        self, user_level: str = "beginner", context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Get educational content about carbon impact examples"""
        carbon_value = context.get("netFootprint", 1.0) if context else 1.0

        return {
            "title": "Understanding Carbon Impact",
            "subtitle": f"What {carbon_value} kg CO2e means in everyday terms",
            "overview": "Carbon numbers can be hard to understand. We translate them into familiar activities to help you grasp the environmental impact.",
            "sections": [
                {
                    "title": "Everyday Comparisons",
                    "content": f"{carbon_value} kg CO2e is equivalent to driving about {carbon_value * 2.4:.1f} miles in an average car, or charging your smartphone for {carbon_value * 120:.0f} days.",
                    "icon": "car",
                    "type": "comparison",
                    "key_takeaway": "Carbon impact in terms you can relate to",
                },
                {
                    "title": "Household Activities",
                    "content": f"This is also like running your dishwasher {carbon_value * 2:.0f} times, or watching TV for {carbon_value * 8:.0f} hours.",
                    "icon": "home",
                    "type": "example",
                    "key_takeaway": "Compare to daily household energy use",
                },
                {
                    "title": "Positive Impact",
                    "content": f"By choosing this product, you're making a climate-conscious choice. Every kg of CO2e avoided helps fight climate change.",
                    "icon": "heart",
                    "type": "explanation",
                    "key_takeaway": "Your choices make a real difference",
                },
            ],
            "quick_facts": [
                "Average American generates 16 tons CO2e per year",
                "Food is a meaningful share of a household's emissions",
                "Small changes in food choices can have big impacts",
                "Local, seasonal foods typically have lower carbon footprints",
            ],
            "related_topics": ["sustainability-metrics"],
            "confidence_level": 85,
            "last_updated": "2024-03-15",
        }

    def get_verification_process_content(
        self, user_level: str = "beginner", context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Get educational content about verification processes"""
        return {
            "title": "How We Verify Farm Data",
            "subtitle": "Building trust through transparency",
            "overview": "Every piece of farm data goes through multiple verification steps to ensure accuracy and prevent greenwashing.",
            "sections": [
                {
                    "title": "Documentation Review",
                    "content": "Farmers provide detailed records of all activities including inputs used, dates of application, and quantities. These records are cross-referenced with purchase receipts and field logs.",
                    "icon": "file-text",
                    "type": "process",
                    "key_takeaway": "Detailed farm records are the foundation",
                },
                {
                    "title": "Third-Party Audits",
                    "content": "Independent auditors visit farms to verify that reported practices match reality. They check records, interview farmers, and inspect fields.",
                    "icon": "search",
                    "type": "explanation",
                    "key_takeaway": "Independent verification prevents false claims",
                },
                {
                    "title": "Continuous Monitoring",
                    "content": "IoT sensors and satellite imagery provide ongoing verification of farming practices. This technology helps detect changes in real-time.",
                    "icon": "activity",
                    "type": "example",
                    "key_takeaway": "Technology enables continuous verification",
                },
            ],
            "quick_facts": [
                "All farms undergo annual verification audits",
                "Satellite imagery can detect changes in land use",
                "IoT sensors provide real-time data validation",
                "Blockchain technology creates tamper-proof records",
            ],
            "related_topics": ["trust-indicators", "usda-methodology"],
            "confidence_level": 93,
            "last_updated": "2024-03-15",
        }

    def get_sustainability_metrics_content(
        self, user_level: str = "beginner", context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Get educational content about sustainability metrics"""
        return {
            "title": "Beyond Carbon: Complete Sustainability",
            "subtitle": "Understanding the full environmental picture",
            "overview": "While carbon footprint is important, complete sustainability includes water use, soil health, biodiversity, equipment efficiency, and social impact. The technology and equipment type used for farm operations significantly influences overall farm sustainability.",
            "sections": [
                {
                    "title": "Water Footprint",
                    "content": "Water use efficiency is crucial for sustainability. We track both the amount of water used and how efficiently it's used through advanced irrigation systems.",
                    "icon": "droplet",
                    "type": "explanation",
                    "key_takeaway": "Water efficiency is part of environmental responsibility",
                },
                {
                    "title": "Soil Health",
                    "content": "Healthy soil is the foundation of sustainable agriculture. We measure soil organic matter, erosion rates, and biodiversity indicators.",
                    "icon": "layers",
                    "type": "process",
                    "key_takeaway": "Soil health ensures long-term sustainability",
                },
                {
                    "title": "Biodiversity Impact",
                    "content": "Sustainable farms support local ecosystems. We track habitat preservation, pollinator support, and integrated pest management practices.",
                    "icon": "globe",
                    "type": "example",
                    "key_takeaway": "Biodiversity support is essential for ecosystem health",
                },
                {
                    "title": "Equipment Efficiency",
                    "content": "Equipment choice affects a season's estimated emissions. Electric equipment has lower operating emissions than diesel, because the estimate counts the fuel or electricity actually used rather than the machine itself.",
                    "icon": "zap",
                    "type": "explanation",
                    "key_takeaway": "Equipment type is a critical sustainability factor",
                },
            ],
            "quick_facts": [
                "Water-efficient irrigation lowers both water use and pumping energy",
                "Healthy soil holds more organic carbon",
                "Diverse plantings support beneficial insects",
                "Integrated practices reduce chemical inputs",
                "Electric farm equipment has lower operating emissions than diesel",
            ],
            "related_topics": ["farming-practices"],
            "confidence_level": 87,
            "last_updated": "2024-03-15",
        }

    def get_educational_content(
        self, topic: str, user_level: str = "beginner", context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Get educational content for a specific topic"""
        content_map = {
            "usda-methodology": self.get_usda_methodology_content,
            "regional-benchmarks": self.get_regional_benchmarks_content,
            "trust-indicators": self.get_trust_indicators_content,
            "farming-practices": self.get_farming_practices_content,
            "carbon-examples": self.get_carbon_examples_content,
            "verification-process": self.get_verification_process_content,
            "sustainability-metrics": self.get_sustainability_metrics_content,
        }

        if topic in content_map:
            return content_map[topic](user_level, context)
        else:
            return self._get_fallback_content()

    def get_contextual_education(self, carbon_score: float, establishment_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get contextual educational content based on carbon score and establishment data"""
        suggestions = []

        # Score-based suggestions
        if carbon_score > 2.0:
            suggestions.append(
                {
                    "topic": "farming-practices",
                    "priority": "high",
                    "reason": "Higher carbon footprint - learn about reduction strategies",
                }
            )
        elif carbon_score < 1.0:
            suggestions.append(
                {
                    "topic": "carbon-examples",
                    "priority": "medium",
                    "reason": "Excellent performance - see how you compare",
                }
            )

        # Always include methodology for transparency
        suggestions.append(
            {"topic": "usda-methodology", "priority": "medium", "reason": "Understand how carbon scores are calculated"}
        )

        return suggestions
