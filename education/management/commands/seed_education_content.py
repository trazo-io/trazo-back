from django.core.management.base import BaseCommand

from education.models import EducationCategory, EducationCourse, EducationLesson, FarmerQuestionAnswer


class Command(BaseCommand):
    help = "Seeds comprehensive educational content for farmers to understand how Trazo works"

    def add_arguments(self, parser):
        parser.add_argument(
            "--refresh",
            action="store_true",
            help=(
                "Rewrite content that already exists. Without this the command is "
                "create-only, so a correction to the copy can never reach an "
                "environment that has been seeded once."
            ),
        )

    def _upsert_course(self, course_data):
        """Return (course, seed_lessons).

        Every caller guards its lesson block with `if created:`, so a re-run was a
        no-op on existing rows. That meant a compliance fix to a lesson — say,
        removing an unsourced "20-30% premium" claim — could be corrected in this
        file and still be served forever from the database. Under --refresh the
        course fields are rewritten and its lessons are rebuilt from scratch.
        """
        course, created = EducationCourse.objects.get_or_create(title=course_data["title"], defaults=course_data)
        if created:
            return course, True
        if not getattr(self, "refresh", False):
            return course, False
        for field, value in course_data.items():
            setattr(course, field, value)
        course.save()
        course.lessons.all().delete()
        return course, True

    def handle(self, *args, **kwargs):
        self.refresh = kwargs.get("refresh", False)
        self.stdout.write(self.style.SUCCESS("Starting education content seeding..."))
        if self.refresh:
            self.stdout.write(self.style.WARNING("--refresh: existing courses and lessons will be rewritten."))

        # Create Categories - Updated for Transparency-First Approach
        categories_data = [
            {
                "name": "Getting Started with Transparency",
                "category_type": "getting_started",
                "description": "Master Trazo's transparency-first approach to build consumer trust",
                "icon": "FaRocket",
                "order": 1,
            },
            {
                "name": "Essential Farm Events Mastery",
                "category_type": "farm_events",
                "description": "Document the 7 core event types for maximum transparency scores",
                "icon": "FaTractor",
                "order": 2,
            },
            {
                "name": "Building Consumer Trust",
                "category_type": "consumer_trust",
                "description": "Create compelling transparency stories that consumers understand",
                "icon": "FaHeart",
                "order": 3,
            },
            {
                "name": "Transparency Technology",
                "category_type": "transparency_tech",
                "description": "Master QR codes, blockchain verification, and mobile documentation",
                "icon": "FaQrcode",
                "order": 4,
            },
            {
                "name": "Market Success Through Transparency",
                "category_type": "market_success",
                "description": "Convert transparency into market position and business value",
                "icon": "FaDollarSign",
                "order": 5,
            },
            {
                "name": "Carbon Data Supporting Role",
                "category_type": "carbon_supporting",
                "description": "Understand carbon calculations as supporting transparency data",
                "icon": "FaLeaf",
                "order": 6,
            },
            {
                "name": "Compliance Made Simple",
                "category_type": "compliance_simple",
                "description": "Meet regulatory requirements through transparent documentation",
                "icon": "FaCertificate",
                "order": 7,
            },
            {
                "name": "Troubleshooting & Success Tips",
                "category_type": "troubleshooting",
                "description": "Common solutions and advanced transparency strategies",
                "icon": "FaQuestionCircle",
                "order": 8,
            },
        ]

        categories = {}
        for cat_data in categories_data:
            category, created = EducationCategory.objects.get_or_create(
                category_type=cat_data["category_type"], defaults=cat_data
            )
            if not created and self.refresh:
                for field, value in cat_data.items():
                    setattr(category, field, value)
                category.save()
            categories[cat_data["category_type"]] = category
            if created:
                self.stdout.write(f"Created category: {category.name}")

        # Create transparency-focused educational content
        self.create_transparency_basics_content(categories)
        self.create_farm_events_mastery_content(categories)
        self.create_consumer_trust_content(categories)
        self.create_transparency_technology_content(categories)
        self.create_market_success_content(categories)
        self.create_carbon_supporting_content(categories)
        self.create_compliance_simple_content(categories)
        self.create_quick_add_mastery_content(categories)
        self.create_transparency_faqs()

        self.stdout.write(self.style.SUCCESS("Successfully seeded comprehensive education content!"))

    def create_transparency_basics_content(self, categories):
        """Create transparency fundamentals course content"""
        course_data = {
            "title": "Transparency Fundamentals: Your Path to Consumer Trust",
            "category": categories["getting_started"],
            "description": "Master Trazo's transparency-first approach to build authentic consumer connections and premium market access",
            "difficulty": "beginner",
            "required_plan": "all",
            "estimated_duration": 45,
            "target_crops": "all crops",
            "farm_size_min": 10,
            "farm_size_max": 1000,
            "is_featured": True,
            "order": 1,
        }

        course, created = self._upsert_course(course_data)

        if created:
            lessons_data = [
                {
                    "title": "Why Transparency Matters More Than Carbon Numbers",
                    "content_type": "video",
                    "duration": 10,
                    "order": 1,
                    "content": """# Trazo's Revolutionary Approach: Transparency-First Farming

## The Game-Changing Shift: More Events = Higher Trust Scores

### Why Traditional Carbon Platforms Failed Farmers
**The Broken Logic:**
- More farming events logged = Higher carbon footprint = Lower scores ❌
- Result: Farmers were PENALIZED for being transparent
- Incentivized hiding farming practices to look better

### Trazo's Innovation: Transparency Rewards
**The Fixed Logic:**
- More farming events logged = Higher transparency score = Higher trust ✅
- Result: Farmers are REWARDED for complete documentation
- Incentivizes full transparency for consumer trust

## What Consumers Really Want
**Research shows:**
- Most consumers cannot interpret a raw CO2e number
- Buyers increasingly ask how their food was grown
- Trust indicators drive 3x more purchase decisions than carbon scores
- A plain-language story holds attention better than technical data

## How Trazo Builds Your Success

### 1. **Transparency Score (Your Primary Metric)**
- Earn 0-100% transparency score
- Higher score = More documented practices = More consumer trust
- Prominent display on consumer QR pages

### 2. **Consumer Trust Building**
- QR codes show your farming story
- Consumers see exact practices used
- Build direct customer relationships
- Transform "commodity" into "premium brand"

### 3. **Carbon Data as Supporting Information**
- Still calculated accurately for B2B customers
- Available for sustainability reporting
- Supports premium market access
- But NOT your primary consumer-facing metric

### 4. **Market Premium Access**
- Documentation supports premium positioning
- Direct consumer sales: documentation supports premium positioning
- Restaurant supplier programs: value provenance they can retell
- Export market differentiation

## Real Farmer Results
- **Consumer Completion Rate:** far more shoppers finish a plain-language page
- **Farmer Engagement:** More comprehensive logging vs hiding practices
- **Trust Building:** Verification badges > carbon scores for purchases
- **Premium Access:** Transparency opens doors carbon couldn't
""",
                    "practical_steps": [
                        "Review your current transparency score in Trazo dashboard",
                        "Log 5 different farming events to see transparency score increase",
                        "Generate your first QR code and scan it to see consumer view",
                        "Compare transparency display vs carbon data prominence",
                        "Share QR code story with family/customers for feedback",
                    ],
                    "cost_savings_potential": "Supports premium positioning through documented practices",
                    "time_savings_potential": "5 minutes per event vs 20-minute manual calculations",
                },
                {
                    "title": "Understanding Transparency Scores: Your New Success Metric",
                    "content_type": "interactive",
                    "duration": 15,
                    "order": 2,
                    "content": """# Transparency Scores: How They Actually Work

## Your New Primary Metric: 0-100% Transparency

### How Transparency Scores are Calculated
**The MORE you document, the HIGHER your score:**

Trazo uses a **weighted category system** that evaluates how thoroughly you document each area of farming:

**Growing Practices (30% of score):**
- Planting, irrigation, harvesting, pruning activities
- More events with complete details = higher category score

**Treatments & Applications (20% of score):**
- Fertilizer, pest control, soil amendments
- Photos are essential — missing photos on chemical events reduces your score significantly

**Soil & Land Care (18% of score):**
- Soil preparation, composting, cover crops
- Demonstrates long-term stewardship to consumers

**Environmental Monitoring (12% of score):**
- Weather events, climate observations
- Shows awareness and adaptation to conditions

**Business & Compliance (10% of score):**
- Certifications, audits, compliance records
- Adds credibility through official documentation

**Photo Evidence (10% of score):**
- Photos are critical — not just a bonus
- **Essential events** (chemical applications) lose up to 50% of their value without photos
- **Recommended events** (production activities) lose up to 25% without photos
- Some events have no photo penalty (irrigation, maintenance)

## Why This Approach Builds Trust

### Consumer Psychology Research
**What consumers actually care about:**
1. "How was this food grown?"
2. "Who grew it and where?"
3. "What practices were used?"
4. "Is it authentic?" (buyers look for concrete trust indicators)
5. "Environmental impact details?" (few shoppers can interpret CO2e)

### Real Example: Two Farmers Comparison
**Farmer A (Traditional Carbon Platform):**
- Logs 5 basic events → Low carbon score → Looks "bad" → Stops logging
- Consumer page: "2.8 kg CO2e per kg" (consumer confused)
- Result: Lower engagement, commodity pricing

**Farmer B (Trazo Transparency):**
- Logs 15 detailed events → 85% transparency score → Looks trustworthy → Logs more
- Consumer page: "85% transparency - 15 farming practices documented"
- Result: higher engagement and stronger premium positioning

## Your Transparency Journey

### Week 1: Transparency Basics (Target: 30%)
- Log 3 production events with photos
- Add 2 chemical or soil management records
- Complete farm profile information

### Week 2-3: Building Documentation (Target: 60%)
- Add chemical application records with photos (essential for score)
- Document business certifications
- Include weather and pest management events

### Month 2: Advanced Transparency (Target: 85%+)
- Comprehensive seasonal documentation
- Photo evidence for all major events (especially chemical applications)
- Consider blockchain verification add-on for tamper-proof records
- Consumer feedback integration

## Impact on Your Business

### Premium Market Access
- **Local/Regional:** documented practices support premium positioning
- **Direct-to-Consumer:** documentation supports premium positioning
- **Restaurant Supply:** chefs value products with a story they can retell
- **Export Markets:** EU transparency requirements compliance

### Consumer Engagement Results
- **Page Views:** 6.5x higher completion rates
- **Trust Building:** Verification badges drive purchases
- **Repeat Customers:** Transparency stories create loyalty
- **Word-of-Mouth:** Authentic stories get shared
""",
                    "practical_steps": [
                        "Check your current transparency score in dashboard",
                        "Log 3 different event types and watch score increase",
                        "Add photos to chemical events — they are essential for maximum scores",
                        "Complete your farm story for consumer QR pages",
                        "Set target transparency score for next month",
                        "Share QR code with friends to get consumer perspective",
                    ],
                },
            ]

            for lesson_data in lessons_data:
                lesson_data["course"] = course
                lesson = EducationLesson.objects.create(**lesson_data)
                self.stdout.write(f"  - Created lesson: {lesson.title}")

    def create_farm_events_mastery_content(self, categories):
        """Create farm events mastery course content"""
        course_data = {
            "title": "7 Essential Farm Events for Maximum Transparency",
            "category": categories["farm_events"],
            "description": "Master all 7 event types to build a record buyers can evaluate",
            "difficulty": "beginner",
            "required_plan": "all",
            "estimated_duration": 60,
            "target_crops": "all crops",
            "is_featured": True,
            "order": 1,
        }

        course, created = self._upsert_course(course_data)

        if created:
            lessons_data = [
                {
                    "title": "Production Events: The Foundation of Agricultural Transparency",
                    "content_type": "interactive",
                    "duration": 15,
                    "order": 1,
                    "content": """# Production Events: Building Trust Through Documentation

## The 4 Core Production Event Types

### 1. **Planting Activities**
**Why Document**: Shows seasonal planning and crop selection decisions
**Consumer Value**: "See how crops are established and planned"
**Best Practices**:
- Log seed variety selections with photos
- Document planting density and spacing
- Include soil preparation activities
- Add GPS coordinates for field mapping

### 2. **Irrigation Events**
**Why Document**: Demonstrates water stewardship and crop care
**Consumer Value**: "Water management affects taste and sustainability"
**Best Practices**:
- Record water sources and quantities
- Document irrigation timing and methods
- Include soil moisture readings when available
- Photo evidence of irrigation systems

### 3. **Harvesting Activities**
**Why Document**: Shows quality control and timing expertise
**Consumer Value**: "Harvest timing determines freshness and flavor"
**Best Practices**:
- Document harvest timing and weather conditions
- Record quality metrics and selection criteria
- Include photos of harvest activities
- Track quantities and storage methods

### 4. **Pruning & Maintenance**
**Why Document**: Shows ongoing crop care and attention
**Consumer Value**: "Regular maintenance ensures healthy crops"
**Best Practices**:
- Log pruning schedules and techniques
- Document equipment usage and maintenance
- Record plant health observations
- Include before/after photos

## Building Your Production Documentation Strategy

### Week 1: Start with Major Events
- Document 2-3 production activities with basic information
- Focus on adding photos and GPS coordinates
- Target: See your Growing Practices category score increase

### Month 1: Comprehensive Coverage
- All production events documented with details
- Regular maintenance activities logged
- Target: 40-60% overall transparency score

### Season 1: Complete Transparency
- Full seasonal production cycle documented
- Consumer-ready production story complete
- Target: 85%+ overall transparency score

## Real Impact on Consumer Trust

### Consumer Research Results:
- **Visual Documentation**: a photo is harder to doubt than a text entry
- **GPS Location**: ties the record to a place, not just a claim
- **Timing Details**: harvest timing tells buyers how fresh the crop is
- **Complete Stories**: Full production cycles drive 3x more engagement

### Premium Market Access:
- **Local Markets**: documented practices support premium positioning
- **Direct Sales**: transparency supports premium positioning
- **Restaurant Supply**: chefs value products with a story they can retell
- **Export Markets**: EU transparency requirements compliance""",
                    "practical_steps": [
                        "Log your next 3 production activities with photos and GPS",
                        "Create a seasonal production calendar for consistency",
                        "Set up photo documentation workflow for all events",
                        "Practice writing consumer-friendly event descriptions",
                        "Check transparency score improvement after logging events",
                    ],
                },
                {
                    "title": "Chemical Applications: Building Consumer Confidence Through Transparency",
                    "content_type": "video",
                    "duration": 20,
                    "order": 2,
                    "content": """# Chemical Applications: Transparency Builds Trust

## Why Chemical Transparency Matters Most

### Consumer Trust Research:
- Chemical applications are the practice buyers ask about most
- **Transparency wins over "zero chemicals"**: Honest documentation beats hiding practices
- **"Reduced Risk" messaging**: a documented practice beats an unknown one
- **Photo evidence**: carries more weight than a text-only description

## The 3 High-Value Chemical Event Types

### 1. **Fertilizer Applications**
**Consumer Concern**: "What nutrients are added and why?"
**Transparency Strategy**:
- Document N-P-K ratios and application rates
- Explain timing: "Applied during active growth for healthy development"
- Include soil test results when available
- **Photos are essential** — chemical events without photos lose up to 50% of their transparency value

### 2. **Pest & Disease Treatments**
**Consumer Concern**: "How are pests managed safely?"
**Transparency Strategy**:
- Document pest identification and threshold levels
- Explain treatment necessity: "Targeted treatment to protect crop quality"
- Record application methods and safety measures
- Include IPM (Integrated Pest Management) context

### 3. **Soil Amendments**
**Consumer Concern**: "How is soil health maintained?"
**Transparency Strategy**:
- Document organic matter additions
- Explain pH adjustments and soil conditioning
- Record application timing and methods
- Include soil health improvement goals

## Photo Evidence Strategy (Essential for Chemical Events)

### Essential Photos to Build Trust:
1. **Before Application**: Show crop condition and pest/disease pressure
2. **During Application**: Demonstrate proper equipment and techniques
3. **After Application**: Document application completion and cleanup
4. **Equipment Close-ups**: Show calibrated sprayers and safety equipment

### Consumer-Friendly Photo Captions:
- "Targeted treatment for aphid pressure to protect crop quality"
- "Soil nutrition application for healthy plant development" 
- "Precision application using calibrated equipment for exact dosing"

## Truth-Telling Strategy That Wins

### What Consumers Actually Want:
1. **Honest Assessment**: Acknowledge challenges and solutions
2. **Clear Explanations**: "Applied fungicide to prevent crop loss from disease"
3. **Safety Measures**: Document protective equipment and application standards
4. **Necessity Justification**: Explain why treatment was needed

### Sample Consumer-Ready Descriptions:
```
"Applied organic approved copper fungicide to prevent late blight disease. 
Treatment applied during early morning to minimize impact on beneficial insects.
Protective equipment used and equipment cleaned after application."
```

## Advanced Transparency Techniques

### Integrated Pest Management (IPM) Documentation:
- **Monitoring**: Regular pest scouting records
- **Thresholds**: When treatment becomes necessary
- **Prevention**: Cultural and biological controls used first
- **Treatment**: Targeted applications as last resort

### Organic & Sustainable Practices:
- Document organic-approved products when used
- Record beneficial insect releases
- Log cover crop applications for soil health
- Include biodiversity enhancement measures

## Building Consumer Confidence

### The Transparency Advantage:
- Buyers trust farms that document their practices
- **Documented practices** beat vague claims like "chemical-free"
- **Photo evidence** creates emotional connection and trust
- **Complete stories** demonstrate farming expertise and care

### Premium Market Access:
- **Transparency**: supports premium positioning with buyers
- **Restaurant partnerships**: Chefs value documented practices
- **Export opportunities**: EU markets require transparency documentation
- **Consumer direct sales**: Transparency drives 3x higher conversion rates""",
                    "practical_steps": [
                        "Document your next chemical application with before/during/after photos",
                        "Practice writing consumer-friendly application justifications",
                        "Create template descriptions for common treatments",
                        "Set up IPM monitoring and documentation workflow",
                        "Test different photo angles and descriptions for maximum trust building",
                    ],
                    "cost_savings_potential": "Documented chemical applications support premium positioning",
                },
            ]

            for lesson_data in lessons_data:
                lesson_data["course"] = course
                lesson = EducationLesson.objects.create(**lesson_data)
                self.stdout.write(f"  - Created lesson: {lesson.title}")

        self.stdout.write(f"Created course: {course.title}")

    def create_consumer_trust_content(self, categories):
        """Create consumer trust building content"""
        course_data = {
            "title": "Building Consumer Trust Through Authentic Storytelling",
            "category": categories["consumer_trust"],
            "description": "Transform farming documentation into compelling stories that consumers trust and value",
            "difficulty": "intermediate",
            "required_plan": "standard",
            "estimated_duration": 40,
            "target_crops": "all crops",
            "is_featured": True,
            "order": 1,
        }

        course, created = self._upsert_course(course_data)

        if created:
            lessons_data = [
                {
                    "title": "QR Code Storytelling: Your Direct Consumer Connection",
                    "content_type": "interactive",
                    "duration": 15,
                    "order": 1,
                    "content": """# QR Code Storytelling: Direct Consumer Connection

## The Power of Instant Agricultural Transparency

### Consumer Behavior Research:
- **Average QR scan to decision**: 78 seconds
- **Trust building window**: First 15 seconds are critical
- **Completion rates**: transparency-first pages hold attention better than carbon-first ones
- **Purchase influence**: Transparency stories drive 3.4x more buying decisions

## Progressive Trust Building Strategy

### Second 1-15: Instant Trust Indicators
**Goal**: Immediate credibility and interest
**Elements**:
- **Transparency Score**: "95% transparency - 12 practices documented"
- **Trust Indicators**: Blockchain-recorded, Photo evidence, GPS location
- **Farm Identity**: "Grown by [Farm Name] in [Location]"
- **Trust Signal**: "All farming practices documented and verified"

### Second 15-45: Story Hook
**Goal**: Emotional connection and understanding
**Elements**:
- **Farmer Introduction**: Personal story and expertise
- **Growing Story**: "This avocado was grown using sustainable irrigation..."
- **Care Highlights**: Key practices that show expertise and care
- **Quality Indicators**: Harvest timing, selection criteria, handling

### Second 45-90: Complete Transparency
**Goal**: Comprehensive understanding and confidence
**Elements**:
- **Production Journey**: Timeline of all documented events
- **Practice Explanations**: Why each decision was made
- **Photo Evidence**: Visual documentation throughout growing cycle
- **Environmental Impact**: Secondary carbon and sustainability data

## Writing Consumer-Friendly Transparency Stories

### Language Guidelines:
**Use**: grown, cared for, nurtured, selected, harvested
**Avoid**: produced, processed, manufactured, optimized

### Sample Transparency Narratives:
```
"This avocado was grown with care on our family farm in California. 
We documented every step from planting to harvest:

🌱 Planted premium Hass variety with sustainable spacing
💧 Watered with precision irrigation to conserve resources  
🍃 Protected with integrated pest management practices
📅 Harvested at perfect ripeness for optimal flavor

Your purchase supports transparent farming practices that build trust between farmers and consumers."
```

## Visual Storytelling with Photos

### Essential Photo Categories:
1. **Farm Identity**: Beautiful farm landscape, farmer portrait
2. **Growing Process**: Key farming activities throughout season
3. **Quality Care**: Close-ups showing attention to detail
4. **Final Product**: Beautiful harvest photos showing quality

### Photo Storytelling Tips:
- **Golden Hour Photography**: Early morning/late afternoon for warmth
- **Action Shots**: Show farming in progress, not static results
- **Scale References**: Include hands, tools to show size and care
- **Before/After**: Show improvement and progress over time

## Trust Signal Optimization

### Primary Trust Signals:
- **Real Farmer Photos**: Actual farmer, not stock photos
- **GPS Verification**: Exact growing location verified
- **Time Stamps**: Real-time documentation dates
- **Blockchain Hash**: Immutable record verification
- **Photo Metadata**: Authentic timestamps and locations

### Secondary Trust Signals:
- **Certification Badges**: Organic, GAP, sustainability certifications
- **Family Story**: Multi-generation farming history
- **Local Recognition**: Community awards or recognition
- **Customer Reviews**: Previous buyer testimonials

## Consumer Psychology of Transparency

### What Builds Trust:
1. **Authenticity**: Real photos, honest challenges, genuine stories
2. **Expertise**: Demonstrated knowledge and proper techniques
3. **Care**: Evidence of attention to detail and quality focus
4. **Transparency**: Complete openness about all practices
5. **Verification**: Third-party validation and proof

### What Breaks Trust:
1. **Generic Content**: Stock photos, template descriptions
2. **Hiding Information**: Incomplete records, missing data
3. **Technical Jargon**: Scientific terms without explanation
4. **Perfection Claims**: Unrealistic "perfect" growing conditions
5. **Inconsistencies**: Conflicting information or dates

## Advanced Storytelling Techniques

### Seasonal Narrative Arc:
- **Spring Planning**: "We selected this variety because..."
- **Summer Care**: "During the growing season, we..."
- **Fall Harvest**: "We knew it was time to harvest when..."
- **Year-Round**: "Our commitment to transparency means..."

### Challenge and Solution Stories:
```
"This growing season brought unusual weather challenges. Here's how we adapted:

When drought conditions threatened our crop in July, we implemented precision 
irrigation scheduling based on soil moisture sensors. This not only saved 
water but ensured optimal fruit development.

Every adjustment was documented and verified, so you can see exactly how we 
protected crop quality while managing resources responsibly."
```

## Measuring Consumer Trust Impact

### Key Metrics to Track:
- **QR Page Completion Rate**: Target >75%
- **Time on Transparency Page**: Target >60 seconds
- **Trust Survey Scores**: Post-scan consumer feedback
- **Purchase Intent**: Measured through follow-up surveys
- **Share Rate**: Consumers sharing transparency stories

### Success Indicators:
- Consumers spending >60 seconds exploring transparency
- 80%+ completion rate through full production story
- Positive feedback mentioning "trust" and "transparency"
- Stronger direct sales and premium positioning
- Customer referrals and story sharing""",
                    "practical_steps": [
                        "Audit your current QR page for trust signals and storytelling flow",
                        "Write 3 practice transparency narratives using consumer-friendly language",
                        "Take 10 high-quality photos showing your farming process and expertise",
                        "Create a seasonal story arc template for your farm's transparency",
                        "Test your QR story with family/friends for clarity and trust building",
                        "Set up metrics tracking for QR page engagement and consumer feedback",
                    ],
                },
            ]

            for lesson_data in lessons_data:
                lesson_data["course"] = course
                lesson = EducationLesson.objects.create(**lesson_data)
                self.stdout.write(f"  - Created lesson: {lesson.title}")

        self.stdout.write(f"Created course: {course.title}")

    def create_transparency_technology_content(self, categories):
        """Create transparency technology content"""
        course_data = {
            "title": "QR Codes, Blockchain & Mobile Documentation Mastery",
            "category": categories["transparency_tech"],
            "description": "Master the technical tools that power Trazo's transparency platform",
            "difficulty": "intermediate",
            "required_plan": "standard",
            "estimated_duration": 35,
            "target_crops": "all crops",
            "is_featured": False,
            "order": 2,
        }

        course, created = self._upsert_course(course_data)

        if created:
            lessons_data = [
                {
                    "title": "Mobile-First Documentation: Your Transparency Toolkit",
                    "content_type": "video",
                    "duration": 18,
                    "order": 1,
                    "content": """# Mobile-First Documentation: Transparency in Your Pocket

## Why Mobile Documentation Works for Farmers

### Real Farmer Benefits:
- **Field-Ready**: Document events as they happen, not hours later
- **Photo Integration**: Instant visual evidence with GPS and timestamps
- **Weather Resistance**: Modern phones work in agricultural conditions
- **Time Savings**: 3 minutes vs 15 minutes for traditional record keeping
- **Accuracy**: Real-time data collection eliminates memory errors

## Essential Mobile Documentation Workflow

### 1. **Pre-Event Setup** (30 seconds)
- Open Trazo app and select event type
- Verify GPS location is active
- Check camera settings for quality photos
- Review event template for required information

### 2. **During Event Documentation** (2 minutes)
- **Before Photos**: Show field/crop condition before activity
- **Action Photos**: Document equipment, materials, techniques
- **Detail Shots**: Close-ups of important specifics
- **Voice Notes**: Quick verbal descriptions while working

### 3. **Post-Event Completion** (1 minute)
- Review photos for quality and completeness
- Add final notes and observations
- Submit for blockchain verification
- Share with team if applicable

## Advanced Mobile Photography for Agricultural Transparency

### Professional Quality Tips:
- **Lighting**: Early morning/late afternoon for best colors
- **Stability**: Use both hands, steady breathing
- **Composition**: Rule of thirds, include context and scale
- **Focus**: Tap screen to focus on key details
- **Multiple Angles**: Wide shot, medium shot, detail shot

### Required Documentation Photos:
1. **Wide Context**: Show field, equipment, and overall scene
2. **Process Documentation**: Step-by-step activity photos
3. **Detail Evidence**: Close-ups of materials, settings, results
4. **Quality Verification**: Final condition and completed work

## GPS and Timestamp Technology

### Why Location Data Builds Trust:
- **Verification**: Proves events happened at claimed location
- **Traceability**: Links products to specific growing areas
- **Compliance**: Meets regulatory requirements for documentation
- **Consumer Confidence**: Verifiable location data increases trust by 67%

### Best Practices for GPS Accuracy:
- Allow location permissions for Trazo app
- Wait for GPS lock before documenting events
- Work in open areas when possible for signal strength
- Verify coordinates match your field maps

## Voice Recording and Transcription

### When to Use Voice Documentation:
- Complex procedures requiring hands-free recording
- Equipment operation that prevents phone handling
- Detailed observations while working
- Quick notes about unexpected conditions or decisions

### Voice Documentation Tips:
- Speak clearly and close to phone microphone
- State date, location, and activity type first
- Describe what you're doing and why
- Include relevant details about conditions and decisions
- Review transcription for accuracy before submitting

## Offline Mode and Data Synchronization

### Why Offline Capability Matters:
- Rural connectivity challenges in many growing regions
- Ensures no data loss during poor signal conditions
- Allows continuous documentation regardless of network
- Automatic sync when connectivity returns

### Offline Best Practices:
- Download area maps before heading to fields
- Pre-load event templates and common materials lists
- Take photos and notes as normal - app stores locally
- Check sync status when returning to WiFi/cellular coverage
- Verify all events uploaded successfully

## Integration with Farm Management Systems

### Streamlined Data Flow:
- Trazo data exports to major farm management platforms
- Reduces duplicate data entry across systems
- Maintains transparency records while supporting operations
- Enables comprehensive reporting and analysis

### Supported Integrations:
- Export to Excel/CSV for custom analysis
- API connections to farm management software
- Automated reporting for certification programs
- Direct sharing with buyers and certification bodies

## Technology Troubleshooting

### Common Issues and Solutions:

**Poor Photo Quality**:
- Clean camera lens regularly
- Ensure adequate lighting
- Use both hands for stability
- Check phone storage space

**GPS Not Working**:
- Enable location services for Trazo app
- Check privacy settings permissions
- Wait for satellite lock in open areas
- Restart app if location seems incorrect

**App Performance Issues**:
- Update app to latest version regularly
- Clear cache if app runs slowly
- Ensure adequate phone storage space
- Contact support for persistent problems

**Data Sync Problems**:
- Check network connectivity
- Verify account login status
- Force sync from settings menu
- Contact support if data missing

## Building Your Mobile Documentation System

### Week 1: Basic Setup
- Download Trazo app and complete profile
- Practice photo documentation for 3 different activities
- Test GPS accuracy in your fields
- Set up offline mode for areas with poor connectivity

### Week 2: Advanced Features
- Practice voice recording and transcription
- Set up integrations with existing farm management
- Create templates for common activities
- Test blockchain verification process

### Month 1: Full Integration
- Document all farming activities through mobile app
- Build library of high-quality activity photos
- Establish routine for daily/weekly documentation
- Monitor transparency score improvements from mobile documentation""",
                    "practical_steps": [
                        "Practice mobile photography techniques in your fields with different lighting conditions",
                        "Document 3 farming activities using voice recording and verify transcription accuracy",
                        "Test offline mode functionality in areas with poor connectivity on your farm",
                        "Set up automated backup and sync preferences in the Trazo app",
                        "Create photo quality standards and train farm team on mobile documentation best practices",
                    ],
                },
                {
                    "title": "Blockchain Recording: Immutable Agricultural Records",
                    "content_type": "interactive",
                    "duration": 17,
                    "order": 2,
                    "content": """# Blockchain Recording: Unbreakable Agricultural Trust

## Understanding Blockchain for Agricultural Transparency

### What Blockchain Actually Does for Your Farm:
- **Immutable Records**: Once recorded, data cannot be altered or deleted
- **Timestamp Verification**: Proves exactly when events were documented
- **Location Verification**: Cryptographic proof of GPS coordinates
- **Photo Authentication**: Prevents tampering with visual evidence
- **Consumer Trust**: Verifiable proof that builds unshakeable confidence

### Why Blockchain Matters for Premium Markets:
- **Export Requirements**: EU and other markets increasingly require verifiable records
- **Premium Positioning**: documented practices give buyers something concrete to evaluate
- **Liability Protection**: Immutable records protect against false claims
- **Consumer Confidence**: an unaltered record is something a buyer can check for themselves

## How Trazo's Blockchain Verification Works

### How It Works (Step by Step):
1. **Document Your Production**: Log all farming events as you normally do (planting, irrigation, fertilization, harvest, etc.)
2. **Finish Your Production**: When you click "Finish Production," Trazo creates a unique digital fingerprint (hash) of ALL your documented events
3. **Automatic Blockchain Submission**: Trazo's system submits this fingerprint to the Polygon blockchain, creating a permanent record
4. **Verification Badge Appears**: Your product's QR code page now displays a "Blockchain-Recorded" badge with a link to the public record
5. **Consumer Verification**: Anyone who scans the QR code can verify the data is authentic through Polygonscan (a public blockchain explorer)

### Important: One Record Per Production
Blockchain verification happens at the **production level**, not per individual event. When your production is finished, one blockchain transaction seals ALL the events documented during that production. This is more cost-effective and gives consumers a complete, verified picture of the entire growing cycle.

### What Gets Verified:
- **All Farming Events**: Every event you documented during the production
- **Carbon Calculations**: The environmental impact data for each activity
- **Production Timeline**: Start date, finish date, and complete event history
- **Data Integrity**: A mathematical fingerprint that proves nothing was changed after finalization

## Polygon Network: Fast, Affordable, Sustainable

### Why Trazo Uses Polygon:
- **Low Cost**: Transactions cost about $0.01 each
- **Fast Confirmation**: Verification complete in seconds
- **Energy Efficient**: 99.95% less energy than traditional blockchain
- **Ethereum Compatible**: Benefits of Ethereum ecosystem without high costs

### Verification Costs:
- **One transaction per production**: Included in the Blockchain Verification add-on
- **No per-event fees**: All events in a production are covered by one transaction
- **No Hidden Fees**: Transparent pricing with no surprise costs
- **Cost**: weigh the add-on cost against what buyer proof is worth to you

## Consumer-Facing Verification Features

### QR Code Verification Elements:
- **Blockchain Badge**: Prominent verification icon on product pages
- **Verification Link**: Direct link to blockchain explorer for technical users
- **Trust Messaging**: "This product's data is verified on blockchain"
- **Verification Date**: Shows when the production was permanently recorded

### Building Consumer Understanding:
```
"Blockchain-Recorded
All farming data for this product has been permanently recorded on blockchain,
ensuring it cannot be altered or falsified. This gives you complete confidence
in the accuracy of agricultural practices used to grow your food."
```

## When Does Verification Happen?

### The Timeline:
1. **During production**: You document events normally. No blockchain activity yet.
2. **You finish the production**: Trazo seals all events with a digital fingerprint (this happens instantly).
3. **Monthly batch processing**: Trazo's system automatically submits all finalized productions to blockchain. This runs on the 1st of each month.
4. **Badge appears**: After the blockchain transaction is confirmed (usually within minutes of submission), consumers see the verification badge on your QR page.

### What This Means For You:
- You don't need to do anything special for blockchain verification. Just document your farming as usual and finish your production when it's ready.
- There may be a short delay between finishing a production and seeing the blockchain badge (up to the next monthly batch run).
- Once verified, the record is permanent and cannot be changed by anyone, including Trazo.

## Setting Up Blockchain Verification

### Requirements:
- **Verified Trazo Account**: Complete farm verification process
- **Blockchain Verification Add-On**: Purchase the add-on from the subscription page
- **Mobile Documentation**: Events must be documented through Trazo app

### Getting Started:
1. **Purchase the Add-On**: Go to your subscription page and add "Blockchain Verification" to your plan
2. **Document as Usual**: Continue logging your farming events through the Trazo app
3. **Finish Your Production**: When your production cycle is complete, click "Finish Production"
4. **Verification Happens Automatically**: Your production will be submitted to blockchain in the next monthly batch
5. **Share With Consumers**: Your QR code page will display the blockchain verification badge

## Verification Best Practices

### Maximizing Verification Value:
- **High-Value Events**: Prioritize verification for critical farming activities
- **Photo Quality**: High-quality photos increase verification credibility
- **Complete Documentation**: Thorough details strengthen verification value
- **Regular Verification**: Consistent verification builds comprehensive trust
- **Consumer Communication**: Actively promote verification to customers

### Common Verification Mistakes:
- **Inconsistent Documentation**: Sporadic verification reduces credibility
- **Poor Photo Quality**: Blurry photos weaken verification impact
- **Missing Details**: Incomplete information reduces transparency value
- **No Consumer Education**: Customers don't understand verification benefits

## Advanced Verification Strategies

### Multi-Signature Verification:
- **Team Verification**: Multiple farm team members verify critical events
- **Third-Party Verification**: Independent verification for premium products
- **Certification Integration**: Link blockchain verification to organic/GAP certifications
- **Supply Chain Verification**: Extend verification through distribution

### Smart Contract Features:
- **Automated Verification**: Trigger verification based on event types
- **Conditional Verification**: Special verification for premium product lines
- **Batch Verification**: Efficient verification for large operations
- **Custom Verification**: Tailored verification for specific market requirements

## Troubleshooting Verification Issues

### Common Problems and Solutions:

**Verification Failed**:
- Check internet connectivity during documentation
- Verify GPS coordinates are accurate
- Ensure photo quality meets minimum standards
- Contact support if problems persist

**High Verification Costs**:
- Review verification settings and frequency
- Use bulk verification for efficiency
- Focus verification on high-value events
- Contact support for cost optimization

**Consumer Confusion**:
- Add verification explanation to product materials
- Create simple guides explaining blockchain benefits
- Use trust messaging that avoids technical jargon
- Provide customer service training on verification

**Technical Integration Issues**:
- Verify farm profile is fully completed
- Check account permissions and settings
- Update Trazo app to latest version
- Contact technical support for integration help

## ROI and Business Impact

### Measurable Benefits:
- **Premium Positioning**: documented products are easier for buyers to justify paying more for
- **Market Access**: Entry to premium and export markets
- **Consumer Trust**: an unaltered record is something a buyer can check
- **Operational Efficiency**: Streamlined record-keeping and compliance
- **Risk Reduction**: Protection against liability and false claims

### Success Stories:
- Growers use blockchain recording where buyers ask for proof the record was not edited
- Organic vegetable operations use documentation to support premium positioning
- Export buyers increasingly ask for records that can be shown to be unaltered
- Automating recordkeeping cuts the hours spent assembling an audit packet""",
                    "practical_steps": [
                        "Enable blockchain verification in your Trazo account settings and document 3 test events",
                        "Review your QR code display to verify blockchain badges appear correctly",
                        "Weigh recording costs against what verifiable proof is worth to your buyers",
                        "Create consumer education materials explaining your blockchain verification",
                        "Set up verification priorities for different types of farming events based on value and importance",
                    ],
                },
            ]

            for lesson_data in lessons_data:
                lesson_data["course"] = course
                lesson = EducationLesson.objects.create(**lesson_data)
                self.stdout.write(f"  - Created lesson: {lesson.title}")

        self.stdout.write(f"Created course: {course.title}")

    def create_market_success_content(self, categories):
        """Create market success content"""
        course_data = {
            "title": "Converting Transparency Into Market Position",
            "category": categories["market_success"],
            "description": "Learn to monetize transparency through premium markets and direct customer relationships",
            "difficulty": "advanced",
            "required_plan": "corporate",
            "estimated_duration": 50,
            "target_crops": "high-value crops",
            "is_featured": True,
            "order": 1,
        }

        course, created = self._upsert_course(course_data)

        if created:
            lessons_data = [
                {
                    "title": "Premium Market Access Through Agricultural Transparency",
                    "content_type": "interactive",
                    "duration": 25,
                    "order": 1,
                    "content": """# Premium Market Access Through Transparency

## The Economics of Agricultural Transparency

### Market Research Data:
- **Premium Positioning**: a more complete record gives buyers more to evaluate
- **Consumer Willingness**: buyers pay more when they can see what they are buying
- **Market Growth**: buyer demand for verifiable sourcing continues to rise
- **Direct Sales**: a page buyers can read converts better than one they cannot

## 4 Premium Market Channels for Transparent Agriculture

### 1. **Direct-to-Consumer Sales**
**Why Transparency Wins**: Consumers buy directly from trusted farmers
**Success Strategy**:
- Prominent transparency scores on product packaging
- QR codes linking to complete farming story
- Social media content showcasing transparent practices
- Customer education about verification and blockchain proof

**Implementation**:
- Set up farm stand or online direct sales
- Create compelling transparency marketing materials
- Build email list of transparency-focused customers
- Develop subscription boxes highlighting seasonal transparency

### 2. **Restaurant and Chef Partnerships**
**Why Chefs Value Transparency**: Authentic farm stories enhance menu appeal
**Success Strategy**:
- Document unique farming techniques and varieties
- Provide seasonal transparency reports to chef partners
- Create chef-exclusive varieties with complete transparency
- Offer farm visits and transparency education for restaurant staff

**Implementation**:
- Approach local farm-to-table restaurants with transparency portfolio
- Create chef-focused transparency presentations
- Develop seasonal transparency calendars for menu planning
- Offer exclusive first access to new transparent varieties

### 3. **Premium Grocery and Specialty Markets**
**Why Retailers Pay Premiums**: Transparency differentiates products on crowded shelves
**Success Strategy**:
- Develop transparency-focused brand identity and packaging
- Provide point-of-sale transparency education materials
- Create in-store transparency demonstrations and tastings
- Build customer loyalty through transparency storytelling

**Implementation**:
- Partner with premium grocers who value transparency
- Develop transparency-focused product positioning
- Create in-store educational materials about farming practices
- Establish transparency-based customer loyalty programs

### 4. **Export and International Markets**
**Why Global Markets Demand Transparency**: Regulatory requirements and consumer expectations
**Success Strategy**:
- Meet international transparency and traceability standards
- Provide documentation whose records can be shown to be unaltered
- Develop region-specific transparency marketing
- Build relationships with international transparency-focused importers

**Implementation**:
- Research target country transparency requirements
- Obtain necessary transparency certifications
- Develop export-ready transparency documentation packages
- Partner with transparency-focused international distributors

## Building Your Transparency Value Proposition

### Core Value Messages:
1. **"Completely Transparent Farming"**: Every practice documented and verified
2. **"Blockchain-Recorded Agricultural Practices"**: Unalterable proof of farming methods
3. **"Full Farm-to-Table Visibility"**: Complete production journey transparency
4. **"Trust Through Technology"**: Advanced verification creates unshakeable confidence

### Quantifying Transparency Benefits:
- **Verification Score**: "95% transparency - 18 farming practices documented"
- **Photo Evidence**: "127 timestamped photos documenting entire growing season"
- **Blockchain Verification**: "All data permanently recorded on blockchain"
- **GPS Verification**: "Exact growing location verified by GPS coordinates"

## Transparency Marketing and Communication

### Consumer-Facing Marketing:
```
"Our 95% Transparency Score Means You Know Everything

✅ 18 farming practices fully documented
✅ 127 photos with timestamps and GPS coordinates  
✅ Blockchain-recorded so the record can be shown to be unaltered
✅ Complete growing story from planting to harvest

Scan the QR code to see exactly how your food was grown."
```

### B2B Sales Materials:
- **Transparency Certificates**: Official documentation of transparency scores
- **Blockchain Verification Reports**: Technical proof of data integrity
- **Seasonal Transparency Summaries**: Complete growing season documentation
- **Compliance Documentation**: Meeting transparency requirements for various markets

## Pricing Strategy for Transparent Products

### Premium Positioning Framework:
- **Base Product**: Market price for conventional equivalent
- **Transparency Premium**: 15-30% based on transparency score and verification level
- **Market Positioning**: Position as premium product, not commodity with markup
- **Value Communication**: Price reflects transparency value, not just production costs

### Dynamic Pricing Strategies:
- **Transparency Score Tiers**: Higher scores command higher premiums
- **Verification Level Pricing**: Blockchain verification adds premium over basic transparency
- **Seasonal Transparency**: Peak transparency seasons command highest premiums
- **Customer Relationship Pricing**: Loyal transparency customers receive value pricing

## Building Long-Term Market Relationships

### Customer Education and Retention:
- **Transparency Tours**: Invite customers to see transparent farming in action
- **Seasonal Updates**: Regular communication about transparency practices
- **Behind-the-Scenes Content**: Show daily transparency documentation process
- **Community Building**: Create community of transparency-focused consumers

### Partnership Development:
- **Mutual Transparency Marketing**: Joint marketing with restaurants/retailers
- **Transparency Events**: Host events showcasing transparent agriculture
- **Industry Leadership**: Become known expert in agricultural transparency
- **Media Relations**: Share transparency success stories with agricultural media

## Measuring and Optimizing Transparency ROI

### Key Performance Indicators:
- **Price Premiums Achieved**: Track premiums vs conventional products
- **Customer Acquisition Cost**: Cost to acquire transparency-focused customers
- **Customer Lifetime Value**: Long-term value of transparency customers
- **Market Share Growth**: Growth in premium transparent product segments

### Optimization Strategies:
- **A/B Testing**: Test different transparency marketing messages
- **Customer Feedback**: Regular feedback on transparency value perception
- **Competitive Analysis**: Monitor competitor transparency strategies
- **Market Research**: Stay informed on transparency market trends

## Scaling Transparency for Business Growth

### Growth Phases:
1. **Phase 1**: Achieve 85%+ transparency scores consistently
2. **Phase 2**: Develop premium market relationships and pricing
3. **Phase 3**: Scale transparency systems for increased production
4. **Phase 4**: Become regional leader in agricultural transparency
5. **Phase 5**: Export transparency leadership to new markets and products""",
                    "practical_steps": [
                        "Conduct market research on transparency premiums in your local area",
                        "Develop transparency-focused value proposition and marketing materials",
                        "Identify and approach 3 potential premium market partners",
                        "Create transparency pricing strategy with specific premium targets",
                        "Set up systems to measure and track transparency ROI and customer feedback",
                    ],
                },
            ]

            for lesson_data in lessons_data:
                lesson_data["course"] = course
                lesson = EducationLesson.objects.create(**lesson_data)
                self.stdout.write(f"  - Created lesson: {lesson.title}")

        self.stdout.write(f"Created course: {course.title}")

    def create_carbon_supporting_content(self, categories):
        """Create carbon supporting role content"""
        course_data = {
            "title": "Carbon Data as Your Supporting Evidence",
            "category": categories["carbon_supporting"],
            "description": "Understand how carbon calculations support transparency while focusing on farmer-controlled emissions",
            "difficulty": "intermediate",
            "required_plan": "standard",
            "estimated_duration": 30,
            "target_crops": "all crops",
            "is_featured": False,
            "order": 3,
        }

        course, created = self._upsert_course(course_data)

        if created:
            lessons_data = [
                {
                    "title": "Understanding Trazo's Farmer-Focused Carbon Approach",
                    "content_type": "interactive",
                    "duration": 15,
                    "order": 1,
                    "content": """# Trazo's Farmer-Focused Carbon Approach

## Why Traditional Carbon Calculations Failed Farmers

### The Transparency Paradox Problem:
**Traditional Approach (BROKEN)**:
- More farming events logged → Higher carbon footprint calculated → Lower score → Farmers penalized for transparency
- Result: Farmers stopped documenting activities to appear "better"

**Trazo's Innovation (FIXED)**:
- More farming events logged → Higher transparency score → Better consumer trust → Farmers rewarded for openness
- Result: Complete agricultural documentation that builds consumer confidence

## Trazo's Focus: Farmer-Controlled Emissions Only

### ✅ What Trazo Calculates (Under Your Control):
1. **Fuel Combustion**: Tractor, harvester, irrigation pump diesel
2. **Fertilizer Applications**: Manufacturing emissions + application fuel
3. **Chemical Applications**: Production emissions + application equipment fuel
4. **On-Farm Energy**: Electricity for irrigation, cooling, processing

### ❌ What Trazo Excludes (Beyond Your Control):
1. **Supply Chain**: Seed transportation, packaging, distribution
2. **Infrastructure**: Farm building construction, equipment manufacturing  
3. **Market Factors**: Consumer transportation, retail energy use
4. **External Systems**: Grid electricity production methods

## The Supporting Role of Carbon Data

### Primary Value: **Transparency Score** (Consumer-Facing)
- "95% transparency - 15 farming practices documented"
- Builds consumer trust and supports premium positioning
- Rewards comprehensive agricultural documentation
- Creates farmer incentive alignment with transparency goals

### Secondary Value: **Carbon Footprint** (B2B Supporting)
- Supporting data for sustainability reporting
- Available for B2B customers who need carbon metrics
- Regulatory compliance when required
- Internal optimization for efficiency improvements

## Consumer-Friendly Carbon Communication

### Instead of Technical Jargon:
**Avoid**: "2.3 kg CO2e per kg product using LCA methodology"
**Use**: "Low environmental impact through efficient farming practices"

**Avoid**: "Scope 1 direct emissions: 1.2 kg CO2e"
**Use**: "Direct farm emissions minimized through precision techniques"

**Avoid**: "USDA emission factors applied"
**Use**: "Environmental impact calculated using government standards"

## When to Emphasize Carbon vs Transparency

### Emphasize **Transparency** (Primary) For:
- **Consumer QR pages**: Lead with transparency score
- **Direct sales**: Focus on documented practices
- **Restaurant partnerships**: Highlight farming story
- **Marketing materials**: Trust through transparency

### Emphasize **Carbon Data** (Secondary) For:
- **B2B sustainability reports**: Carbon metrics for supply chain
- **Compliance requirements**: When regulation requires carbon data
- **Internal optimization**: Efficiency improvements and cost savings
- **Grant applications**: Environmental impact documentation

## Progressive Disclosure Strategy

### Layer 1: Trust Building (First 15 seconds)
- **Transparency Score**: "95% transparency"
- **Record integrity**: "Blockchain-recorded practices"
- **Photo Count**: "23 documented farming activities"

### Layer 2: Story Understanding (15-45 seconds)
- **Farming Practices**: What you did and why
- **Care and Expertise**: Evidence of quality focus
- **Seasonal Journey**: Complete growing story

### Layer 3: Technical Details (45+ seconds, expandable)
- **Carbon Footprint**: For interested consumers
- **Environmental Impact**: Specific metrics and improvements
- **Technical Verification**: Methodology and standards used

## Building Consumer Understanding

### Consumer Education Framework:
1. **Start with Trust**: Transparency score and verification
2. **Build Understanding**: Farming story and practices
3. **Provide Depth**: Environmental impact for interested consumers
4. **Enable Verification**: Technical data available for transparency

### Sample Progressive Messaging:
```
Primary: "95% Transparency - See exactly how this food was grown"
Secondary: "Low environmental impact through precision farming"
Technical: "2.1 kg CO2e per kg (23% below industry average)"
```

## Carbon Data for Business Operations

### Internal Benefits:
- **Cost Optimization**: Identify fuel and input inefficiencies
- **Operational Planning**: Track environmental impact improvements
- **Compliance Readiness**: Prepared for future carbon regulations
- **Grant Applications**: Environmental documentation for funding

### B2B Communication:
- **Supply Chain Partners**: Provide carbon data for corporate reporting
- **Certification Bodies**: Environmental impact documentation
- **Regulatory Agencies**: Compliance data when required
- **Sustainability Consultants**: Input for carbon management strategies

## The Future of Agricultural Carbon Data

### Emerging Trends:
- **Transparency-First Markets**: Consumer trust over carbon scores
- **Blockchain Verification**: Immutable environmental records
- **Real-Time Documentation**: Continuous farming practice verification
- **Consumer Education**: Growing understanding of agricultural practices

### Preparing for Evolution:
- **Build Comprehensive Records**: Document everything for future requirements
- **Focus on Farmer Control**: Emphasize emissions you can actually manage
- **Maintain Dual Approach**: Transparency primary, carbon supporting
- **Stay Updated**: Monitor market and regulatory developments

This approach ensures carbon data supports your transparency story rather than replacing it, while providing the technical foundation needed for various business and regulatory requirements.""",
                    "practical_steps": [
                        "Review your current carbon footprint data in the context of transparency scoring",
                        "Practice explaining carbon data as supporting evidence rather than primary metric",
                        "Set up progressive disclosure on your QR pages with transparency first, carbon details secondary",
                        "Create consumer-friendly explanations of your environmental impact improvements",
                        "Prepare B2B carbon reports for customers who specifically request carbon data",
                    ],
                },
            ]

            for lesson_data in lessons_data:
                lesson_data["course"] = course
                lesson = EducationLesson.objects.create(**lesson_data)
                self.stdout.write(f"  - Created lesson: {lesson.title}")

        self.stdout.write(f"Created course: {course.title}")

    def create_compliance_simple_content(self, categories):
        """Create simplified compliance content"""
        course_data = {
            "title": "Compliance Through Daily Transparency Logging",
            "category": categories["compliance_simple"],
            "description": "Meet regulatory requirements effortlessly through comprehensive transparency documentation",
            "difficulty": "beginner",
            "required_plan": "all",
            "estimated_duration": 25,
            "target_crops": "all crops",
            "is_featured": False,
            "order": 4,
        }

        course, created = self._upsert_course(course_data)

        if created:
            lessons_data = [
                {
                    "title": "Transparency Documentation as Automatic Compliance",
                    "content_type": "interactive",
                    "duration": 25,
                    "order": 1,
                    "content": """# Transparency Documentation as Automatic Compliance

## How Transparency Simplifies Compliance

### The Traditional Compliance Burden:
- **Separate Paperwork**: Different forms for different agencies
- **Manual Record Keeping**: Time-consuming documentation requirements
- **Audit Preparation**: Stressful preparation for inspector visits
- **Missing Records**: Lost paperwork leads to compliance problems

### Trazo's Transparency Solution:
- **One Documentation System**: Single platform meets multiple requirements
- **Real-Time Records**: Instant documentation as you farm
- **Automatic Audit Trail**: Blockchain verification creates unalterable records
- **Export-Ready Reports**: Generate compliance reports with one click

## Key Compliance Areas Covered by Transparency

### 1. **Chemical Application Records**
**Requirements Met**:
- EPA pesticide application documentation
- Organic certification chemical tracking
- Worker protection safety records
- State agriculture department reporting

**Trazo Documentation Provides**:
- Exact chemical names and concentrations
- Application dates, times, and weather conditions
- Operator certification and safety equipment used
- GPS coordinates and field maps with photo evidence

### 2. **Food Safety and Traceability**
**Requirements Met**:
- FDA Food Safety Modernization Act (FSMA)
- Good Agricultural Practices (GAP) certification
- USDA National Organic Program (NOP)
- Export market traceability requirements

**Trazo Documentation Provides**:
- Complete production chain documentation
- Harvest dates and handling procedures
- Equipment cleaning and maintenance records
- Worker training and hygiene protocols with photo evidence

### 3. **Organic Certification Compliance**
**Requirements Met**:
- USDA Organic certification record keeping
- Buffer zone documentation and monitoring
- Input approval verification and tracking
- Inspection preparation and annual reporting

**Trazo Documentation Provides**:
- All input applications with approved substance verification
- Field maps with GPS boundaries and buffer zones
- Equipment cleaning and separation protocols
- Complete audit trail with blockchain verification

### 4. **Environmental and Water Quality**
**Requirements Met**:
- EPA Water Quality Protection Plans
- State environmental agriculture regulations
- Nutrient management plan compliance
- Groundwater protection monitoring

**Trazo Documentation Provides**:
- Irrigation scheduling and water source records
- Fertilizer application rates and timing with soil testing
- Runoff prevention measures and monitoring
- Equipment calibration and application accuracy records

## Building Compliance Through Daily Transparency

### Week 1: Foundation Setup
- **Profile Completion**: Complete farm and field profiles with GPS boundaries
- **Input Inventory**: Record all chemicals, fertilizers, and equipment in system
- **Team Training**: Train all farm workers on mobile documentation
- **Basic Events**: Start documenting daily activities with photos

### Month 1: Comprehensive Documentation
- **All Applications**: Document every chemical and fertilizer application
- **Equipment Maintenance**: Record calibration and cleaning protocols
- **Worker Training**: Document safety training and certification updates
- **Quality Control**: Implement photo evidence for all compliance activities

### Season 1: Full Compliance System
- **Audit Preparation**: System automatically generates inspection reports
- **Certification Renewal**: Export complete documentation for certifier review
- **Regulatory Reporting**: Generate required reports for state and federal agencies
- **Continuous Improvement**: Use transparency data to optimize compliance efficiency

## Automatic Report Generation

### Available Compliance Reports:
1. **Chemical Application Summary**: EPA and state pesticide reporting
2. **Organic Production Records**: Complete NOP compliance documentation
3. **Food Safety Plan Updates**: FSMA-compliant production records
4. **Water Quality Monitoring**: Environmental protection documentation
5. **Worker Safety Compliance**: Training and safety protocol records

### Report Features:
- **PDF Export**: Professional format for inspector submission
- **Blockchain Verification**: Each report includes verification hash
- **Custom Date Ranges**: Generate reports for any time period
- **Multiple Formats**: Excel, PDF, and API export options
- **Audit Trail**: Complete chain of custody for all data

## Inspector and Auditor Benefits

### What Inspectors See:
- **Real-Time Data**: No paper records to lose or forge
- **Photo Evidence**: Visual verification of compliance activities
- **GPS Verification**: Exact location data for all documented events
- **Blockchain Proof**: Mathematical proof of data integrity
- **Historical Tracking**: Complete multi-year compliance history

### Inspection Preparation Simplified:
```
Traditional Preparation (40+ hours):
- Gather paper records from multiple locations
- Create summary reports manually
- Organize by compliance requirement
- Hope nothing is missing or illegible

Trazo Preparation (30 minutes):
- Generate compliance report by date range
- Export blockchain-recorded documentation
- Share secure digital access with inspector
- All data organized automatically by requirement
```

## Cost Savings and Efficiency Gains

### Traditional Compliance Costs:
- **Record Keeping**: 10-15 hours per month manual documentation
- **Audit Preparation**: 40-60 hours before each inspection
- **Missed Deadlines**: Potential fines and certification delays
- **Lost Records**: Re-documentation and inspection delays

### Trazo Compliance Benefits:
- **Real-Time Documentation**: 2-3 minutes per farming activity
- **Automatic Audit Preparation**: 30 minutes to generate complete reports
- **No Missed Deadlines**: Automated reminders and reporting
- **Perfect Record Keeping**: Blockchain verification eliminates lost data

## Future-Proofing Your Compliance

### Emerging Regulations:
- **Carbon Reporting**: Increasing requirements for environmental impact documentation
- **Supply Chain Transparency**: Consumer and regulatory demand for traceability
- **Blockchain Verification**: Government adoption of digital verification
- **International Standards**: Export market transparency requirements

### Staying Ahead:
- **Comprehensive Documentation**: Document everything for future requirements
- **Technology Integration**: Stay current with digital documentation standards
- **Continuous Improvement**: Use transparency data to exceed compliance minimums
- **Industry Leadership**: Become example of best practices in agricultural documentation

## Common Compliance Challenges Solved

### Problem: "We lost the paperwork for last month"
**Solution**: Blockchain verification creates permanent, unalterable records that cannot be lost

### Problem: "Inspector wants records we don't typically keep"
**Solution**: Comprehensive transparency documentation captures data for requirements you didn't know existed

### Problem: "Certification renewal is a nightmare"
**Solution**: One-click export generates complete certification documentation with verification

### Problem: "Workers forget to document activities"
**Solution**: Mobile apps make documentation faster and easier than traditional methods

### Problem: "Different agencies want different formats"
**Solution**: Same data exports to multiple formats for different regulatory requirements

## Building a Culture of Compliance Excellence

### Team Training Approach:
1. **Show Value**: Demonstrate how transparency documentation reduces workload
2. **Make It Easy**: Provide mobile tools that work in field conditions
3. **Reward Excellence**: Recognize team members for thorough documentation
4. **Lead by Example**: Farmers and managers model best practices
5. **Continuous Learning**: Regular updates on new compliance benefits

This approach transforms compliance from a burden into a competitive advantage, creating documentation that exceeds regulatory requirements while building consumer trust and premium market access.""",
                    "practical_steps": [
                        "Audit current compliance requirements and identify gaps in documentation",
                        "Set up Trazo profiles for all farm operations and input all required compliance information",
                        "Train farm team on mobile compliance documentation using Trazo app",
                        "Generate test compliance reports for your major certification and regulatory requirements",
                        "Create inspection preparation checklist using Trazo's automated report features",
                    ],
                },
            ]

            for lesson_data in lessons_data:
                lesson_data["course"] = course
                lesson = EducationLesson.objects.create(**lesson_data)
                self.stdout.write(f"  - Created lesson: {lesson.title}")

        self.stdout.write(f"Created course: {course.title}")

    def create_quick_add_mastery_content(self, categories):
        """Create Quick Add Event mastery course content"""
        course_data = {
            "title": "Quick Add Event Mastery: Fast Transparency Logging",
            "category": categories["farm_events"],
            "description": "Master the Quick Add Event feature to log farming activities in under 60 seconds with full transparency scoring",
            "difficulty": "beginner",
            "required_plan": "all",
            "estimated_duration": 25,
            "target_crops": "all crops",
            "is_featured": True,
            "order": 2,
        }

        course, created = self._upsert_course(course_data)

        if created:
            lessons_data = [
                {
                    "title": "Quick Add in 60 Seconds: Your Fastest Path to Transparency",
                    "content_type": "video",
                    "duration": 8,
                    "order": 1,
                    "content": """# Quick Add Event: Log Farm Activities in Under 60 Seconds

## Why Quick Add Changes Everything

### The Traditional Problem:
- Manual event logging takes 5-10 minutes per event
- Complex forms discourage consistent documentation
- Farmers skip logging = Lower transparency scores
- Incomplete records = weaker position with buyers

### The Quick Add Solution:
- **3-tap event creation**: Select type → Add details → Submit
- **Smart defaults**: Pre-filled values based on your farm profile
- **Photo-ready**: Camera integration for instant visual evidence
- **Voice capture**: Speak your event details hands-free
- **AI suggestions**: Intelligent recommendations based on season and crop

## How Quick Add Works

### Step 1: Choose Your Method (5 seconds)
**Three Fast Ways to Start:**
1. **📝 Smart Templates**: Pre-configured for 7 event types with AI-powered crop-specific suggestions
2. **🎤 Voice Capture**: Speak naturally — AI pre-fills key fields from your description
3. **✨ AI Suggestions**: Let Trazo recommend based on your farm and season

### Step 2: Select Event Type (10 seconds)
**7 Event Types Available:**
- 🌱 **Production**: Planting, irrigation, harvesting, pruning, equipment use
- 🧪 **Chemical**: Fertilizer, pesticide, herbicide, fungicide applications
- 🌍 **Soil Management**: Soil tests, amendments, compost, cover crops
- 🐛 **Pest Management**: Pest monitoring, biological controls, IPM
- 🌦️ **Weather**: Frost, drought, hail, wind, climate observations
- 📋 **Business**: Certifications, audits, compliance records
- 📝 **General**: Agronomist visits, field observations, technical notes

### Step 3: Add Details (30-40 seconds)
**Smart Forms Show Only What Matters:**
- **Type-aware fields**: Only see relevant fields for your event type
- **Smart defaults**: Pre-filled based on your past activities
- **Quick photo**: One tap to add timestamped visual evidence
- **Optional depth**: Add more details only if needed

### Step 4: Review & Submit (10 seconds)
**Before You Submit:**
- Preview your event card (exactly as consumers will see it)
- Verify photo quality and GPS location
- Check description is consumer-friendly
- Submit with one tap

## Quick Add Best Practices

### For Maximum Transparency Impact:
1. **Add Photos**: Photos are essential for chemical events — missing them can reduce your score by up to 50%
2. **Use Clear Descriptions**: Write for consumers, not farm records
3. **Log Same Day**: Real-time documentation is most credible
4. **Include Context**: Weather conditions, reasons for activity

### Sample Quick Add Flow:
```
[Open Quick Add] → [Select "Chemical"] →
[Smart form shows: product, NPK ratio, volume, method] →
[Take photo of application] →
[Preview shows: "Fertilizer application - organic compost..."] →
[Submit] → Done! Event logged in under 60 seconds
```

## Voice Capture: Get a Head Start on Documentation

### When to Use Voice:
- **In the field**: While operating equipment
- **Busy hands**: During application activities
- **Quick notes**: Capturing observations on the go

### How Voice Capture Works:
1. Tap microphone icon in Quick Add
2. Speak naturally: "Applied organic fertilizer to field 3, about 50 pounds per acre"
3. AI pre-fills key fields from your description (typically 4-7 fields)
4. **Review the pre-filled form** — add photos and complete remaining details
5. Submit when everything looks correct

### Important: Voice is a Fast-Start Tool
- Voice pre-fills key fields but does **not** create a fully documented event
- For maximum transparency scores, review and complete all fields after voice capture
- Always add photos for chemical events — they are essential for your score
- The Manual Add flow creates the most complete documentation

### Voice Tips:
- Speak clearly near your phone
- Include: what, where, how much, why
- Mention weather or special conditions
- Always review and add details after voice capture

## AI Smart Suggestions

### Seasonal Intelligence:
Trazo suggests events based on:
- Current growing season for your crops
- Weather patterns in your area
- Your past documentation patterns
- Common practices for your farm type

### How to Use Suggestions:
1. Open Quick Add during work hours
2. See "Suggested for today" panel
3. Tap suggestion to pre-fill form
4. Customize details and submit

## Transparency Score Impact

### How Events Affect Your Score:
Your transparency score uses a **weighted category system**:
- **Growing Practices** (30%): Production events like planting, irrigation, harvest
- **Treatments** (20%): Chemical applications — photos are essential here
- **Soil & Land Care** (18%): Soil management activities
- **Environmental** (12%): Weather events and monitoring
- **Business** (10%): Certifications and compliance
- **Photo Evidence** (10%): Photos across all events, especially chemical

### Weekly Goal:
**Log 5-7 events per week** to maintain steady transparency growth
- Average farm: 85%+ score achievable in 30 days
- Daily logging: Just 3-5 minutes total
- Positioning: a more complete record gives buyers more to evaluate""",
                    "practical_steps": [
                        "Open Quick Add and create your first event using smart templates",
                        "Test all 3 creation methods: templates, voice capture, and AI suggestions",
                        "Always add photos to chemical events — they are essential for your score",
                        "Set a daily reminder to log at least 1 event per farm activity day",
                        "Check your transparency score before and after logging 5 events",
                    ],
                },
                {
                    "title": "Choosing the Right Event Type: A Decision Guide",
                    "content_type": "interactive",
                    "duration": 10,
                    "order": 2,
                    "content": """# Choosing the Right Event Type

## The 7 Event Types Explained

### Understanding Event Categories

Quick Add offers **7 event types** that cover all farming activities:

**Production Events:**
- Core farming activities: planting, irrigation, harvesting, pruning, equipment use
- The foundation of your Growing Practices category score (30% of total)
- Most common daily logging events

**Chemical Events:**
- Fertilizer, pesticide, herbicide, and fungicide applications
- Consumer interest is highest here — photos are essential
- Missing photos on chemical events can reduce their transparency value by up to 50%

**Supporting Events:**
- Soil Management, Pest Management, Weather, Business, and General
- Round out your transparency story across all weighted categories

## Event Type Decision Guide

### 🌱 Planting Events
**Use When:**
- Sowing seeds directly in field
- Transplanting seedlings
- Establishing new crop areas
- Cover crop seeding

**Key Fields:**
- Crop variety and source
- Planting density/spacing
- Soil preparation done
- Seeds/seedlings quantity

**Consumer Value:** "See exactly how crops are established"

---

### 💧 Irrigation Events
**Use When:**
- Running irrigation system
- Manual watering activities
- Adjusting irrigation schedule
- Emergency drought response

**Key Fields:**
- Water volume applied
- Irrigation method (drip, sprinkler, flood)
- Duration of irrigation
- Area covered

**Consumer Value:** "Water stewardship and resource management"

---

### 🌿 Fertilization Events (Chemical - FE)
**Use When:**
- Applying synthetic fertilizers
- Spreading organic compost/manure
- Foliar feeding applications
- Soil amendment applications

**Key Fields:**
- NPK ratio or composition
- Volume/weight applied
- Application method
- Area treated

**Consumer Value:** "Nutrient management for healthy crops"

---

### 🐛 Pest Control Events (Chemical - PE)
**Use When:**
- Applying insecticides
- Using biological controls
- IPM interventions
- Beneficial insect releases

**Key Fields:**
- Product name and type
- Concentration/rate
- Target pest identified
- Safety measures taken

**Consumer Value:** "Crop protection with transparency"

---

### 🌾 Herbicide Events (Chemical - HE)
**Use When:**
- Pre-emergent weed control
- Post-emergent herbicide application
- Organic weed management
- Cover crop termination

**Key Fields:**
- Herbicide product and type
- Volume applied
- Target weeds
- Application method

**Consumer Value:** "Weed management practices documented"

---

### 🍄 Fungicide Events (Chemical - FU)
**Use When:**
- Preventive disease treatment
- Curative fungicide application
- Organic disease control
- Soil fungicide treatment

**Key Fields:**
- Fungicide product and type
- Volume applied
- Target disease
- Application timing

**Consumer Value:** "Disease prevention and crop health"

---

### 🔧 Pruning Events (Production)
**Use When:**
- Seasonal pruning activities
- Maintenance trimming
- Thinning fruit/flowers
- Training young plants

**Key Fields:**
- Equipment used
- Fuel consumed (if powered)
- Area covered
- Purpose/reason

**Consumer Value:** "Crop care and quality management"

---

### 📦 Harvest Events (Production)
**Use When:**
- Crop collection activities
- Recording yields
- Quality sorting
- Post-harvest handling

**Key Fields:**
- Yield quantity and unit
- Equipment used
- Transportation distance
- Quality observations

**Consumer Value:** "Harvest timing and handling transparency"

## Quick Decision Flowchart

```
What are you doing?
│
├─ Applying something to crops?
│   ├─ Nutrients/fertilizer → 🌿 Fertilization
│   ├─ For insects/pests → 🐛 Pest Control
│   ├─ For weeds → 🌾 Herbicide
│   └─ For disease → 🍄 Fungicide
│
├─ Working with plants directly?
│   ├─ Putting plants in ground → 🌱 Planting
│   ├─ Cutting/trimming → 🔧 Pruning
│   └─ Collecting crop → 📦 Harvest
│
└─ Managing water?
    └─ Any watering activity → 💧 Irrigation
```

## Multiple Events in One Day

### It's Normal to Log Multiple Events!
- Morning irrigation + afternoon fertilization = 2 events
- Harvest from field A + planting in field B = 2 events
- Pest scouting + treatment = 2 events (scouting can be general observation)

### Batch Logging Tip:
If you did multiple activities, Quick Add supports sequential logging:
1. Complete first event → Submit
2. Tap "Add Another Event"
3. Select next type → Complete → Submit
4. Each event adds to transparency score""",
                    "practical_steps": [
                        "Review the 7 event types and identify which apply to your farm operations",
                        "Log one event from each applicable category over the next week",
                        "Practice using the decision flowchart for your next 3 field activities",
                        "Set up Quick Add templates for your most common event types",
                        "Test logging multiple events in one session using batch logging",
                    ],
                },
                {
                    "title": "Photos That Build Consumer Trust",
                    "content_type": "video",
                    "duration": 7,
                    "order": 3,
                    "content": """# Photos That Build Consumer Trust

## Why Photos Matter in Quick Add

### The Trust Multiplier:
- Photos increase consumer trust by **67%**
- **Essential events** (chemical applications) lose up to **50%** of their transparency value without photos
- **Recommended events** (production activities) lose up to **25%** without photos
- Visual evidence creates emotional connection
- Timestamped photos prove authenticity

## Quick Photo Best Practices

### The 3-Photo Rule
For maximum impact, capture:

**1. Context Photo (Wide)**
- Shows overall scene: field, equipment, conditions
- Establishes scale and location
- 3-5 seconds to capture

**2. Action Photo (Medium)**
- Shows the activity in progress
- Equipment being used, materials visible
- 3-5 seconds to capture

**3. Detail Photo (Close-up)**
- Shows specific details: labels, measurements, results
- Product labels, calibration settings, crop condition
- 3-5 seconds to capture

### One-Photo Quick Option
When time is limited, prioritize:
- **Chemical events**: Product label or equipment
- **Production events**: Crop or field condition
- **Harvest events**: Product quality and quantity

## Photo Tips by Event Type

### 🌿 Fertilization Photos
**Best shots:**
- Product bag/label with NPK visible
- Spreader or application equipment
- Field coverage pattern

### 🐛 Pest Control Photos
**Best shots:**
- Target pest (if visible)
- Product label and safety equipment
- Application in progress

### 💧 Irrigation Photos
**Best shots:**
- Irrigation system running
- Soil moisture before/after
- Water source or controller

### 📦 Harvest Photos
**Best shots:**
- Harvest in progress
- Yield quantity/bins
- Product quality close-up

## Technical Photo Quality

### For Clear, Usable Photos:
- **Lighting**: Early morning or late afternoon best
- **Stability**: Use both hands, brace elbows
- **Focus**: Tap screen on subject before shooting
- **Clean lens**: Quick wipe removes field dust

### Auto-Captured Metadata:
Trazo automatically records:
- ✅ GPS coordinates (verifies location)
- ✅ Date and time (proves timing)
- ✅ Device info (authenticity check)

## Consumer Photo Impact

### What Consumers See:
- Your photos appear in production journey timeline
- Timestamped captions show farming expertise
- Multiple photos show thoroughness and care
- Photo quality reflects professionalism

### Building Visual Trust Story:
```
Example Consumer View:
┌─────────────────────────────────┐
│ 📷 June 15 - Organic Fertilizer │
│    Application                  │
│ ┌───────────────────────────┐   │
│ │  [Photo: Farmer spreading │   │
│ │   organic compost]        │   │
│ └───────────────────────────┘   │
│ "Applied organic compost for    │
│  healthy soil and nutrient      │
│  development. Our commitment    │
│  to sustainable farming."       │
│                                 │
│ 🔒 Verified • 📍 Farm Field 3   │
└─────────────────────────────────┘
```

## Quick Add Photo Workflow

### Fastest Photo Process:
1. **Before event**: Quick context photo (5 sec)
2. **During event**: Start Quick Add form
3. **Mid-form**: Tap camera icon
4. **Capture**: Take 1-3 photos
5. **Continue**: Complete form fields
6. **Submit**: All photos auto-attached

### Photo Storage:
- Photos stored securely in Trazo
- Compressed for fast loading on consumer QR pages
- Original quality preserved for verification
- Automatic backup prevents loss""",
                    "practical_steps": [
                        "Practice the 3-photo rule on your next farm activity",
                        "Test Quick Add photo workflow: open form → add photos → complete",
                        "Review your recent events and identify which could use better photos",
                        "Set up your phone camera for quick access during field work",
                        "Take sample photos in different lighting conditions to understand quality",
                    ],
                },
            ]

            for lesson_data in lessons_data:
                lesson_data["course"] = course
                lesson = EducationLesson.objects.create(**lesson_data)
                self.stdout.write(f"  - Created lesson: {lesson.title}")

        self.stdout.write(f"Created course: {course.title}")

    def create_transparency_faqs(self):
        """Create transparency-focused FAQ entries"""
        faqs_data = [
            {
                "question": "What does a complete season record look like?",
                "answer": """A complete season covers seven kinds of records — the same map your certifier's reviewer works through:

**The Seven Categories:**
- Growing Practices: Planting, irrigation, harvest, pruning
- Treatments & Applications: Fertilizer, pest control, amendments
- Soil & Land Care: Soil preparation, composting, cover crops
- Pest Management: Scouting, traps, beneficial releases
- Business & Compliance: Certifications, audits, inspections
- Weather and General: Observations and everything else

**Photos are evidence, not decoration** — planting, harvest, and chemical applications are where an inspector most wants a photo behind the entry.

**Where to check yourself:** the readiness card on your farm home lists what is missing before your certifier asks. Buyers and shoppers never see any score — they see the documented practices themselves.""",
                "category": "records",
                "is_featured": True,
            },
            {
                "question": "Do I need special equipment to document transparency?",
                "answer": """No special equipment required! Trazo works with:

**Basic Level:** Just your smartphone for photos and event logging
**With location:** Smartphone GPS auto-fills the parcel and weather context

**Getting Started:** most farmers start with their phone and see their documentation completeness improve within the first week of logging events.""",
                "category": "setup",
                "is_featured": False,
            },
            {
                "question": "How do consumers actually use the transparency information?",
                "answer": """When someone scans your QR code, they see your records — not a rating:

**What Consumers See:**
- Documented practices: each activity in plain words, with its date
- Farming story: your farm description, in your words, labeled as yours
- Photo evidence: timestamped photos from the field
- Certifications: USDA Organic shows "Verified" only when it matches the USDA Organic Integrity Database; anything else is labeled "Self-Reported"
- Carbon data (secondary): available in an expandable section, never the headline

**What consumers do NOT see:** any score, grade, or rating. Your transparency score is a producer-dashboard tool; the public page shows the facts it is built from.""",
                "category": "consumer_page",
                "is_featured": False,
            },
            # Logging activities — matches the LIVE "Add event → What did you do?"
            # verb-tile flow (WS-4). The old "Quick Add Event" feature name and the
            # backend 7-type taxonomy are retired from farmer-facing copy: farmers
            # pick a VERB; the seven record categories appear only as list filters.
            {
                "question": "How do I log an activity?",
                "answer": """From your parcel or the Activities page, press **Add event**. Three steps:

1. **What did you do?** Pick the activity tile — Planting, Input application, Irrigation, Field work, Harvest, Equipment cleanout, Soil & amendments, Pest & scouting, Weather event, Sales & compliance, or Other activity — and set the date
2. **Details** — the form asks only what that activity needs; templates and voice can pre-fill most of it
3. **Photos** — optional but powerful; add them for planting, harvest, and input applications especially

Most activities take under two minutes. Everything you log builds the same record your certifier reviews and your renewal packet assembles from.""",
                "category": "quick_add",
                "is_featured": True,
            },
            {
                "question": "Which activity type should I choose?",
                "answer": """Pick the tile that matches what happened in the field:

- **Input application** — any fertilizer, pesticide, fungicide, herbicide, or amendment you applied (product, rate, and area are captured here)
- **Planting / Harvest** — crop in, crop out; harvest also records quantity, destination, and buffer-row disposition
- **Irrigation** — water source, method, and duration
- **Soil & amendments** — soil tests, compost, cover crops
- **Pest & scouting** — monitoring walks, traps, beneficial releases
- **Equipment cleanout** — what was cleaned and how; this is your commingling-prevention record (7 CFR 205.272)
- **Sales & compliance** — certifications, inspections, audits, sales records
- **Weather event / Field work / Other activity** — context and everything else

**Quick decision:** applying something to the crop or soil? Input application. Working with the plants themselves? Planting or Harvest.""",
                "category": "quick_add",
                "is_featured": False,
            },
            {
                "question": "Can I use voice or templates to log faster?",
                "answer": """Yes — both live inside the activity form:

- **Voice**: speak it the way you'd say it — "Applied 200 pounds of zinc sulfate on the north block" — and Trazo pre-fills 4-7 fields from your words. You review before saving
- **Templates**: crop-specific accelerators pre-fill typical values for common activities; you adjust the numbers to match the day

Whatever the entry method, you confirm every field — the record is yours.""",
                "category": "quick_add",
                "is_featured": False,
            },
            {
                "question": "How do I add photos to an activity?",
                "answer": """The photo step is the last step of every activity form — snap from your phone in the field or upload later.

**Where photos matter most:** planting, harvest, and input applications — those are the records where an inspector most wants visual evidence behind the entry. A product-label photo on an input application answers the "what exactly did you apply?" question before it is asked.""",
                "category": "quick_add",
                "is_featured": False,
            },
            {
                "question": "How does each activity build my season record?",
                "answer": """Each activity you log lands in the season file your certifier reviews:

**How Categories Work:**
- Growing Practices: Planting, irrigation, harvest, pruning events
- Treatments: Input applications — photos essential here
- Soil & Land Care: Soil management activities
- Pest Management: Scouting and control activities
- Business: Certifications and compliance
- Weather and General: Observations and everything else

**Key Tip:** Photos matter most on essential events — an input application with its label photo answers the inspector's question before it is asked.

**Weekly Goal for Success:**
- Log 5-7 activities per week for steady coverage
- Time required: Just 3-5 minutes daily total

**The payoff:** at renewal time, your OSP modules and packet draft themselves from what you logged — and the readiness card shows any gaps while there is still time to close them.""",
                "category": "quick_add",
                "is_featured": False,
            },
            {
                "question": "How do I build my Organic System Plan in Trazo?",
                "answer": """Open **Organic System Plan** in the sidebar. Your OSP is a set of guided modules that follow the Common OSP structure — seeds, soil, pest management, harvest, storage, recordkeeping, and more.

**How it works:**
- Answer each module as a short questionnaire, in English or Spanish
- Where Trazo can suggest an answer from your season's records, it shows the suggestion **with the evidence named** — you confirm or edit it; nothing is ever auto-saved
- Topics that don't apply get an explicit Not Applicable attestation, so "skipped" never looks like "forgotten"
- Completed modules become PDFs, and the whole plan assembles into a renewal packet

You are the author of your plan — Trazo makes sure nothing is missing when your certifier asks.""",
                "category": "osp_renewal",
                "is_featured": True,
            },
            {
                "question": "What deadlines matter for renewal season?",
                "answer": """The window runs October to April, and the exact dates depend on your certifier — always confirm with them. Typical recent windows:

- **CCOF**: annual update opens early November, due January 1
- **PCO**: mid-January - **MOSA**: early February - **OTCO**: January 1 or April 1
- **OCCSP cost-share**: applications historically due **December 31** at your county FSA office — reimburses a share of certification costs (verify current-year terms)

**The practical rule:** reconcile your records in the postharvest window, while the season is still fresh. Trazo's readiness card shows what is missing while there is still time to close the gaps.""",
                "category": "osp_renewal",
                "is_featured": True,
            },
            {
                "question": "I'm coming from COG Pro — how do I move my records?",
                "answer": """COG Pro has announced it will end service December 31, 2026. Your organic records must stay retrievable for **5 years** (7 CFR 205.103(b)(4)), so export everything before the shutdown — field lists, input applications, harvest logs, and sales records, covering the full retention window.

Trazo imports COG Pro CSV exports **white-glove**: send us the export and your records arrive as structured activities, linked to your parcels. Their Field maps to a Trazo parcel; Row/Section identifiers land on each activity's block ID.""",
                "category": "records",
                "is_featured": False,
            },
            {
                "question": "How does my certifier see my records?",
                "answer": """Two ways, and you control both:

- **The renewal packet** — module PDFs, per-parcel applications, workbooks, and the audit PDF, generated on demand and filed in your Documents
- **A live review link** — a read-only page you can share that opens your current records in the browser: activity log, inputs with National List cross-references, and documents. No account needed on their side, and it always shows the records as they stand today

Trazo never sends anything to your certifier on its own — sharing is always your action.""",
                "category": "records",
                "is_featured": False,
            },
        ]

        # Questions renamed over time: get_or_create keys on question text, so the
        # old rows must be removed or the FAQ list serves both generations forever.
        LEGACY_QUESTIONS = [
            "How does transparency scoring actually work?",
            "How does Quick Add affect my transparency score?",
            # 2026-08-09: "Quick Add Event" feature name retired (WS-7); questions
            # re-authored around the live verb-tile flow.
            "What is Quick Add Event and how does it work?",
            "Which event type should I choose in Quick Add?",
            "How do I add photos in Quick Add?",
            "Can I use voice to create events in Quick Add?",
            "What are smart defaults in Quick Add?",
            "How does Quick Add build my season record?",
        ]
        FarmerQuestionAnswer.objects.filter(question__in=LEGACY_QUESTIONS).delete()

        for faq_data in faqs_data:
            faq, created = FarmerQuestionAnswer.objects.get_or_create(question=faq_data["question"], defaults=faq_data)
            if not created and getattr(self, "refresh", False):
                for field, value in faq_data.items():
                    setattr(faq, field, value)
                faq.save()
            if created:
                self.stdout.write(f"Created FAQ: {faq.question[:50]}...")
