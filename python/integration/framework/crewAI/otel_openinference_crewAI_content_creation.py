# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import time
import os
import json
import random

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# OpenAI env
os.environ['OPENAI_BASE_URL'] = 'https://ark.cn-beijing.volces.com/api/v3' # use ark model url
os.environ['OPENAI_API_KEY'] = '***' # your ark api key, from https://www.volcengine.com/docs/82379/1361424

# OTEL env
os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = "https://api.coze.cn/v1/loop/opentelemetry/v1/traces" # cozeloop otel endpoint
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "cozeloop-workspace-id=***,Authorization=Bearer ***" # set your 'spaceID' and 'pat or sat token'

# OTEL configuration
otlp_exporter = OTLPSpanExporter(
    timeout=10,
)
trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)
tracer = trace.get_tracer(__name__)

# OpenInference auto-detection
try:
    from openinference.instrumentation.crewai import CrewAIInstrumentor
    from openinference.instrumentation.litellm import LiteLLMInstrumentor
    
    CrewAIInstrumentor().instrument(skip_dep_check=True)
    LiteLLMInstrumentor().instrument()
    print("✅ OpenInference auto-detection enabled")
except ImportError as e:
    print(f"⚠️  OpenInference auto-detection import failed: {e}")
    print("Program will continue running, but without OTEL tracing functionality")

from crewai import Agent, Task, Crew, LLM
from crewai.tools import tool

# ==================== LOCAL TOOLS IMPLEMENTATION ====================

# Research Tools
@tool("search_trending_topics")
def search_trending_topics(topic: str) -> str:
    """Search for trending topics and keywords related to the given topic
    
    Args:
        topic: The main topic to search for trending keywords
        
    Returns:
        JSON string containing trending insights and opportunities
    """
    # Simulate trending topics search with realistic data
    trending_data = {
        "artificial intelligence": {
            "trending_keywords": ["AI automation", "machine learning trends", "generative AI", "AI ethics", "AI in healthcare"],
            "search_volume": {"high": 5, "medium": 8, "low": 12},
            "related_questions": ["What is AI automation?", "How does machine learning work?", "What are the benefits of AI?"],
            "content_opportunities": ["AI in healthcare", "Future of work with AI", "AI ethics and governance"]
        },
        "technology": {
            "trending_keywords": ["cloud computing", "cybersecurity", "blockchain", "IoT", "5G technology"],
            "search_volume": {"high": 7, "medium": 10, "low": 15},
            "related_questions": ["What is cloud computing?", "How secure is blockchain?", "What is IoT?"],
            "content_opportunities": ["Cloud migration strategies", "Cybersecurity best practices", "IoT implementation"]
        },
        "marketing": {
            "trending_keywords": ["digital marketing", "content marketing", "social media marketing", "SEO", "email marketing"],
            "search_volume": {"high": 8, "medium": 12, "low": 20},
            "related_questions": ["How to improve SEO?", "What is content marketing?", "How to use social media for business?"],
            "content_opportunities": ["SEO optimization guide", "Social media strategy", "Email marketing automation"]
        }
    }
    
    # Find matching topic or use default
    topic_lower = topic.lower()
    data = None
    for key in trending_data:
        if key in topic_lower or topic_lower in key:
            data = trending_data[key]
            break
    
    if not data:
        data = {
            "trending_keywords": [f"{topic} trends", f"{topic} best practices", f"{topic} guide"],
            "search_volume": {"high": 3, "medium": 6, "low": 10},
            "related_questions": [f"What is {topic}?", f"How to use {topic}?", f"Benefits of {topic}?"],
            "content_opportunities": [f"{topic} implementation", f"{topic} strategies", f"{topic} case studies"]
        }
    
    result = {
        "main_topic": topic,
        "trending_keywords": data["trending_keywords"],
        "search_volume": data["search_volume"],
        "related_questions": data["related_questions"],
        "content_opportunities": data["content_opportunities"],
        "trend_score": random.randint(75, 95)
    }
    
    return json.dumps(result, indent=2)

@tool("fact_check_content")
def fact_check_content(claims: str) -> str:
    """Verify factual claims and statements for accuracy
    
    Args:
        claims: Text content containing claims to be fact-checked
        
    Returns:
        JSON string containing fact-checking results and recommendations
    """
    # Simulate fact-checking analysis
    word_count = len(claims.split())
    claim_count = len([s for s in claims.split('.') if s.strip()])
    
    # Simulate verification based on content characteristics
    verified_facts = max(1, int(claim_count * 0.8))
    questionable_claims = max(0, claim_count - verified_facts)
    fact_accuracy = min(95, max(70, 85 + random.randint(-10, 10)))
    
    result = {
        "total_claims_analyzed": claim_count,
        "verified_facts": verified_facts,
        "questionable_claims": questionable_claims,
        "fact_accuracy_percentage": fact_accuracy,
        "source_recommendations": [
            "Industry research reports",
            "Academic publications",
            "Government statistics",
            "Authoritative news sources"
        ],
        "corrections_needed": [
            "Verify latest statistics",
            "Update outdated information",
            "Add source citations"
        ] if fact_accuracy < 85 else ["No major corrections needed"],
        "credibility_score": round(fact_accuracy / 10, 1)
    }
    
    return json.dumps(result, indent=2)

@tool("gather_statistics")
def gather_statistics(topic: str) -> str:
    """Collect relevant statistics and data points for the given topic
    
    Args:
        topic: The topic to gather statistics for
        
    Returns:
        JSON string containing key statistics and data sources
    """
    # Simulate statistics gathering with realistic data patterns
    stats_database = {
        "artificial intelligence": [
            "73% of businesses use AI in some capacity (McKinsey, 2024)",
            "AI market expected to reach $1.8 trillion by 2030 (Gartner)",
            "60% increase in AI adoption since 2020 (IBM Research)",
            "AI can improve productivity by up to 40% (Accenture)"
        ],
        "technology": [
            "Digital transformation spending to reach $2.8 trillion by 2025 (IDC)",
            "95% of organizations have a cloud strategy (Flexera)",
            "Cybersecurity spending increased by 12% in 2024 (Gartner)",
            "IoT devices expected to reach 75 billion by 2025 (Statista)"
        ],
        "marketing": [
            "Content marketing costs 62% less than traditional marketing (HubSpot)",
            "Email marketing ROI averages $42 for every $1 spent (Litmus)",
            "70% of marketers actively invest in content marketing (HubSpot)",
            "Social media marketing budgets increased by 25% in 2024 (Sprout Social)"
        ]
    }
    
    # Find relevant statistics
    topic_lower = topic.lower()
    key_statistics = []
    for key in stats_database:
        if key in topic_lower or any(word in topic_lower for word in key.split()):
            key_statistics = stats_database[key]
            break
    
    if not key_statistics:
        key_statistics = [
            f"{topic} adoption rate increased by 35% in 2024",
            f"Market size for {topic} projected to grow 20% annually",
            f"85% of professionals consider {topic} important for their industry"
        ]
    
    result = {
        "topic": topic,
        "key_statistics": key_statistics,
        "data_sources": [
            "McKinsey Global Institute",
            "Gartner Research",
            "IDC Market Analysis",
            "Industry Association Reports"
        ],
        "charts_suggested": [
            f"{topic} adoption trends over time",
            f"Market size growth projection",
            f"Industry comparison analysis"
        ],
        "data_freshness": "2024 latest data",
        "credibility_score": round(random.uniform(8.5, 9.8), 1)
    }
    
    return json.dumps(result, indent=2)

# Strategy Tools
@tool("analyze_target_audience")
def analyze_target_audience(topic: str) -> str:
    """Analyze target audience demographics and preferences for the given topic
    
    Args:
        topic: The topic to analyze audience for
        
    Returns:
        JSON string containing audience analysis and recommendations
    """
    # Simulate audience analysis based on topic
    audience_profiles = {
        "artificial intelligence": {
            "primary_audience": "Tech professionals and business leaders aged 25-45",
            "knowledge_level": "Intermediate to Advanced",
            "preferred_content_length": "1200-1800 words",
            "engagement_preferences": ["practical examples", "case studies", "implementation guides"],
            "content_tone": "Professional yet accessible",
            "reading_time_preference": "5-8 minutes"
        },
        "technology": {
            "primary_audience": "IT professionals and technology enthusiasts aged 22-50",
            "knowledge_level": "Beginner to Advanced",
            "preferred_content_length": "800-1500 words",
            "engagement_preferences": ["tutorials", "comparisons", "best practices"],
            "content_tone": "Technical but clear",
            "reading_time_preference": "4-7 minutes"
        },
        "marketing": {
            "primary_audience": "Marketing professionals and business owners aged 25-40",
            "knowledge_level": "Beginner to Intermediate",
            "preferred_content_length": "1000-1600 words",
            "engagement_preferences": ["actionable tips", "success stories", "tools and resources"],
            "content_tone": "Engaging and practical",
            "reading_time_preference": "5-6 minutes"
        }
    }
    
    # Find matching profile or create default
    topic_lower = topic.lower()
    profile = None
    for key in audience_profiles:
        if key in topic_lower or any(word in topic_lower for word in key.split()):
            profile = audience_profiles[key]
            break
    
    if not profile:
        profile = {
            "primary_audience": f"Professionals interested in {topic} aged 25-45",
            "knowledge_level": "Beginner to Intermediate",
            "preferred_content_length": "1000-1500 words",
            "engagement_preferences": ["practical examples", "step-by-step guides", "real-world applications"],
            "content_tone": "Professional and informative",
            "reading_time_preference": "5-7 minutes"
        }
    
    result = {
        "topic": topic,
        "primary_audience": profile["primary_audience"],
        "knowledge_level": profile["knowledge_level"],
        "preferred_content_length": profile["preferred_content_length"],
        "engagement_preferences": profile["engagement_preferences"],
        "content_tone": profile["content_tone"],
        "reading_time_preference": profile["reading_time_preference"],
        "device_preferences": ["Desktop (60%)", "Mobile (35%)", "Tablet (5%)"],
        "social_platforms": ["LinkedIn", "Twitter", "Medium", "Industry forums"]
    }
    
    return json.dumps(result, indent=2)

@tool("generate_seo_keywords")
def generate_seo_keywords(topic: str) -> str:
    """Generate SEO-optimized keywords and meta tags for the given topic
    
    Args:
        topic: The main topic to generate SEO keywords for
        
    Returns:
        JSON string containing SEO keywords and optimization recommendations
    """
    # Generate SEO keywords based on topic

    # Primary keywords (high competition, high volume)
    primary_keywords = [
        topic.lower(),
        f"{topic.lower()} guide",
        f"{topic.lower()} best practices",
        f"how to use {topic.lower()}"
    ]
    
    # Secondary keywords (medium competition, good volume)
    secondary_keywords = [
        f"{topic.lower()} tips",
        f"{topic.lower()} strategies",
        f"{topic.lower()} examples",
        f"{topic.lower()} implementation",
        f"{topic.lower()} benefits",
        f"what is {topic.lower()}"
    ]
    
    # Long-tail keywords (low competition, targeted)
    long_tail_keywords = [
        f"how to implement {topic.lower()} effectively",
        f"best {topic.lower()} practices for beginners",
        f"{topic.lower()} vs alternatives comparison",
        f"step by step {topic.lower()} guide"
    ]
    
    # Generate meta information
    meta_title = f"{topic}: Complete Guide & Best Practices 2024"
    meta_description = f"Discover everything about {topic.lower()}. Learn best practices, implementation strategies, and expert tips. Complete guide with practical examples."
    
    result = {
        "topic": topic,
        "primary_keywords": primary_keywords,
        "secondary_keywords": secondary_keywords,
        "long_tail_keywords": long_tail_keywords,
        "meta_title": meta_title,
        "meta_description": meta_description,
        "keyword_density_target": "1.5-2.5%",
        "focus_keyword": topic.lower(),
        "internal_linking_opportunities": [
            "Related topic articles",
            "Resource pages",
            "Case study pages",
            "Tool comparison pages"
        ],
        "seo_score_potential": random.randint(75, 90)
    }
    
    return json.dumps(result, indent=2)

@tool("create_content_outline")
def create_content_outline(topic: str, audience_data: str) -> str:
    """Create a comprehensive content outline based on topic and audience analysis
    
    Args:
        topic: The main topic for the content
        audience_data: JSON string containing audience analysis data
        
    Returns:
        JSON string containing detailed content outline
    """
    # Parse audience data if provided
    try:
        audience = json.loads(audience_data) if audience_data.startswith('{') else {}
    except:
        audience = {}
    
    # Determine content length based on audience preferences
    target_length = 1200  # default
    if "preferred_content_length" in audience:
        length_range = audience["preferred_content_length"]
        if "1200-1800" in length_range:
            target_length = 1500
        elif "800-1500" in length_range:
            target_length = 1200
        elif "1000-1600" in length_range:
            target_length = 1300
    
    # Create outline structure
    sections = [
        {
            "header": "Introduction",
            "word_count": int(target_length * 0.15),
            "key_points": ["Hook to grab attention", "Problem statement", "Article preview", "Value proposition"],
            "purpose": "Engage readers and set expectations"
        },
        {
            "header": f"What is {topic}?",
            "word_count": int(target_length * 0.20),
            "key_points": ["Definition and explanation", "Key characteristics", "Why it matters", "Common misconceptions"],
            "purpose": "Establish foundational understanding"
        },
        {
            "header": f"Benefits and Applications of {topic}",
            "word_count": int(target_length * 0.25),
            "key_points": ["Primary benefits", "Real-world applications", "Success stories", "Industry use cases"],
            "purpose": "Demonstrate value and relevance"
        },
        {
            "header": f"Best Practices for {topic}",
            "word_count": int(target_length * 0.25),
            "key_points": ["Step-by-step approach", "Expert recommendations", "Common pitfalls to avoid", "Implementation tips"],
            "purpose": "Provide actionable guidance"
        },
        {
            "header": "Conclusion and Next Steps",
            "word_count": int(target_length * 0.15),
            "key_points": ["Key takeaways summary", "Action items", "Additional resources", "Call to action"],
            "purpose": "Reinforce value and encourage action"
        }
    ]
    
    result = {
        "title": f"The Complete Guide to {topic}: Best Practices and Implementation",
        "sections": sections,
        "total_word_count": target_length,
        "estimated_read_time": f"{int(target_length / 200)} minutes",
        "content_structure": "Problem-Solution-Action format",
        "tone_guidelines": audience.get("content_tone", "Professional and informative"),
        "target_audience": audience.get("primary_audience", f"Professionals interested in {topic}"),
        "seo_optimization": "Include primary keyword in H1 and H2 headers"
    }
    
    return json.dumps(result, indent=2)

# Writing Tools
@tool("write_engaging_intro")
def write_engaging_intro(topic: str, hook_type: str = "question") -> str:
    """Generate compelling opening hooks and introductions
    
    Args:
        topic: The main topic for the introduction
        hook_type: Type of hook to use (question, statistic, story, quote)
        
    Returns:
        JSON string containing introduction options and engagement strategies
    """
    # Generate different types of hooks
    hooks = {
        "question": f"What if {topic.lower()} could transform your business operations overnight?",
        "statistic": f"Did you know that 73% of companies using {topic.lower()} report significant improvements in efficiency?",
        "story": f"When Sarah first encountered {topic.lower()}, she was skeptical. Six months later, it had revolutionized her entire workflow.",
        "quote": f"As industry expert John Smith once said, '{topic} is not just a trend—it's the future of how we work.'"
    }
    
    # Generate value propositions
    value_props = [
        f"Learn how to leverage {topic.lower()} for maximum impact",
        f"Discover the secrets that top professionals use with {topic.lower()}",
        f"Master {topic.lower()} with our comprehensive guide",
        f"Transform your approach to {topic.lower()} with proven strategies"
    ]
    
    # Create introduction structure
    intro_structure = [
        "Opening hook to capture attention",
        "Brief context about the topic's importance",
        "Problem statement or challenge",
        "Preview of what readers will learn",
        "Value proposition and benefits"
    ]
    
    result = {
        "topic": topic,
        "hook_options": {
            "question_hook": hooks["question"],
            "statistic_hook": hooks["statistic"],
            "story_hook": hooks["story"],
            "quote_hook": hooks["quote"]
        },
        "selected_hook_type": hook_type,
        "value_propositions": value_props,
        "introduction_structure": intro_structure,
        "tone_guidelines": "Conversational yet professional",
        "engagement_score": random.randint(80, 95),
        "word_count_target": "150-200 words"
    }
    
    return json.dumps(result, indent=2)

@tool("create_call_to_action")
def create_call_to_action(content_goal: str) -> str:
    """Design effective CTAs for different content goals
    
    Args:
        content_goal: The primary goal of the content (lead generation, engagement, sales, etc.)
        
    Returns:
        JSON string containing CTA options and optimization recommendations
    """
    # Define CTA strategies based on goals
    cta_strategies = {
        "lead generation": {
            "primary_cta": "Download our free comprehensive guide",
            "secondary_cta": "Subscribe for weekly expert insights",
            "urgency_elements": ["Limited time offer", "Exclusive access", "Join 10,000+ professionals"]
        },
        "engagement": {
            "primary_cta": "Share your thoughts in the comments",
            "secondary_cta": "Follow us for more insights",
            "urgency_elements": ["Join the conversation", "Be part of the community", "Share your experience"]
        },
        "education": {
            "primary_cta": "Start implementing these strategies today",
            "secondary_cta": "Bookmark this guide for future reference",
            "urgency_elements": ["Take action now", "Don't wait to get started", "Begin your journey today"]
        },
        "sales": {
            "primary_cta": "Get started with our premium solution",
            "secondary_cta": "Schedule a free consultation",
            "urgency_elements": ["Limited time discount", "Book your spot today", "Only 10 spots remaining"]
        }
    }
    
    # Select strategy based on goal
    goal_lower = content_goal.lower()
    strategy = cta_strategies.get("education")  # default
    for key in cta_strategies:
        if key in goal_lower:
            strategy = cta_strategies[key]
            break
    
    # Generate placement recommendations
    placement_suggestions = [
        "After the introduction",
        "Middle of the article (natural break)",
        "End of the article",
        "In a sidebar or callout box"
    ]
    
    result = {
        "content_goal": content_goal,
        "primary_cta": strategy["primary_cta"],
        "secondary_cta": strategy["secondary_cta"],
        "placement_suggestions": placement_suggestions,
        "urgency_elements": strategy["urgency_elements"],
        "design_recommendations": [
            "Use contrasting colors",
            "Make buttons prominent",
            "Keep text concise and action-oriented",
            "Test different variations"
        ],
        "conversion_potential": "High" if "sales" in goal_lower else "Medium",
        "a_b_test_variations": [
            "Button vs text link",
            "Different wording options",
            "Color variations",
            "Placement alternatives"
        ]
    }
    
    return json.dumps(result, indent=2)

@tool("format_content")
def format_content(raw_content: str) -> str:
    """Apply proper formatting and styling to content for better readability
    
    Args:
        raw_content: The raw content text to be formatted
        
    Returns:
        JSON string containing formatted content and formatting recommendations
    """
    # Analyze content structure
    paragraphs = [p.strip() for p in raw_content.split('\n\n') if p.strip()]
    word_count = len(raw_content.split())
    
    # Apply basic formatting rules
    formatted_paragraphs = []
    for i, paragraph in enumerate(paragraphs):
        # Add headers for major sections
        if i == 0:
            formatted_paragraphs.append(f"# {paragraph}")
        elif len(paragraph.split()) > 50 and any(keyword in paragraph.lower() for keyword in ['what is', 'benefits', 'how to', 'conclusion']):
            formatted_paragraphs.append(f"## {paragraph}")
        else:
            # Break long paragraphs
            if len(paragraph.split()) > 100:
                sentences = paragraph.split('. ')
                mid_point = len(sentences) // 2
                part1 = '. '.join(sentences[:mid_point]) + '.'
                part2 = '. '.join(sentences[mid_point:])
                formatted_paragraphs.extend([part1, part2])
            else:
                formatted_paragraphs.append(paragraph)
    
    # Generate formatting recommendations
    formatting_applied = []
    if word_count > 800:
        formatting_applied.append("Added section headers")
    if any(len(p.split()) > 100 for p in paragraphs):
        formatting_applied.append("Split long paragraphs")
    
    formatting_applied.extend([
        "Applied markdown formatting",
        "Improved readability structure",
        "Added proper spacing"
    ])
    
    # Suggest improvements
    image_suggestions = [
        "Header image for the article",
        "Infographic summarizing key points",
        "Screenshots or diagrams if applicable",
        "Charts or graphs for data visualization"
    ]
    
    readability_improvements = [
        "Use bullet points for lists",
        "Add subheadings every 200-300 words",
        "Include transition sentences",
        "Bold important keywords"
    ]
    
    result = {
        "original_word_count": word_count,
        "formatted_content": '\n\n'.join(formatted_paragraphs),
        "formatting_applied": formatting_applied,
        "image_suggestions": image_suggestions,
        "readability_improvements": readability_improvements,
        "seo_formatting": [
            "Use H1 for main title",
            "Use H2 for section headers",
            "Include focus keyword in headers",
            "Add alt text for images"
        ],
        "mobile_optimization": "Content formatted for mobile readability"
    }
    
    return json.dumps(result, indent=2)

# Quality Assurance Tools
@tool("check_grammar_style")
def check_grammar_style(content: str) -> str:
    """Perform comprehensive grammar and style checks on content
    
    Args:
        content: The content text to be checked
        
    Returns:
        JSON string containing grammar analysis and style recommendations
    """
    # Analyze content characteristics
    word_count = len(content.split())
    sentence_count = len([s for s in content.split('.') if s.strip()])
    avg_sentence_length = word_count / max(sentence_count, 1)
    
    # Simulate grammar checking
    errors_found = max(0, int(word_count / 200) + random.randint(-2, 3))
    
    # Generate grammar score based on content quality indicators
    grammar_score = 10.0
    if avg_sentence_length > 25:
        grammar_score -= 0.5
    if errors_found > 5:
        grammar_score -= 1.0
    grammar_score = max(7.0, grammar_score - (errors_found * 0.2))
    
    # Generate style analysis
    style_consistency = "Excellent" if grammar_score >= 9.0 else "Good" if grammar_score >= 8.0 else "Needs Improvement"
    
    # Common corrections (simulated)
    corrections = []
    if avg_sentence_length > 20:
        corrections.append({"type": "sentence length", "suggestion": "Consider breaking long sentences into shorter ones"})
    if word_count > 1000 and "however" not in content.lower():
        corrections.append({"type": "transitions", "suggestion": "Add transition words between paragraphs"})
    if errors_found > 0:
        corrections.append({"type": "punctuation", "suggestion": "Review comma usage and punctuation"})
    
    result = {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "average_sentence_length": round(avg_sentence_length, 1),
        "grammar_score": round(grammar_score, 1),
        "style_consistency": style_consistency,
        "errors_found": errors_found,
        "corrections": corrections,
        "style_recommendations": [
            "Maintain consistent tone throughout",
            "Use active voice where possible",
            "Vary sentence structure for engagement",
            "Ensure proper paragraph transitions"
        ],
        "overall_quality": "Professional" if grammar_score >= 8.5 else "Good" if grammar_score >= 7.5 else "Needs Improvement"
    }
    
    return json.dumps(result, indent=2)

@tool("validate_content_flow")
def validate_content_flow(content: str) -> str:
    """Analyze logical content progression and narrative structure
    
    Args:
        content: The content text to analyze for flow and structure
        
    Returns:
        JSON string containing flow analysis and structural recommendations
    """
    # Analyze content structure
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    paragraph_count = len(paragraphs)
    
    # Check for transition indicators
    transition_words = ['however', 'therefore', 'furthermore', 'additionally', 'consequently', 'meanwhile', 'moreover']
    transition_count = sum(1 for word in transition_words if word in content.lower())
    
    # Analyze logical progression
    has_intro = any(keyword in paragraphs[0].lower() for keyword in ['introduction', 'what is', 'overview']) if paragraphs else False
    has_conclusion = any(keyword in paragraphs[-1].lower() for keyword in ['conclusion', 'summary', 'takeaway']) if paragraphs else False
    
    # Calculate flow score
    flow_score = 7.0  # base score
    if has_intro:
        flow_score += 0.5
    if has_conclusion:
        flow_score += 0.5
    if transition_count >= paragraph_count * 0.3:
        flow_score += 1.0
    if paragraph_count >= 4:
        flow_score += 0.5
    
    flow_score = min(10.0, flow_score)
    
    # Determine quality levels
    transition_quality = "Excellent" if transition_count >= paragraph_count * 0.4 else "Good" if transition_count >= paragraph_count * 0.2 else "Needs Improvement"
    logical_progression = "Clear" if flow_score >= 8.0 else "Adequate" if flow_score >= 7.0 else "Unclear"
    
    # Generate recommendations
    weak_connections = []
    if transition_count < paragraph_count * 0.2:
        weak_connections.append("Add more transition words between sections")
    if not has_intro:
        weak_connections.append("Add a clear introduction")
    if not has_conclusion:
        weak_connections.append("Include a strong conclusion")
    
    structural_suggestions = [
        "Ensure each paragraph has a clear main point",
        "Use topic sentences to introduce new concepts",
        "Connect ideas with appropriate transitions",
        "Build arguments progressively"
    ]
    
    result = {
        "paragraph_count": paragraph_count,
        "transition_words_found": transition_count,
        "flow_score": round(flow_score, 1),
        "transition_quality": transition_quality,
        "logical_progression": logical_progression,
        "has_clear_intro": has_intro,
        "has_strong_conclusion": has_conclusion,
        "weak_connections": weak_connections if weak_connections else ["No major issues identified"],
        "structural_suggestions": structural_suggestions,
        "narrative_coherence": "Strong" if flow_score >= 8.5 else "Adequate" if flow_score >= 7.0 else "Weak"
    }
    
    return json.dumps(result, indent=2)

@tool("calculate_readability_score")
def calculate_readability_score(content: str) -> str:
    """Calculate readability metrics and provide accessibility recommendations
    
    Args:
        content: The content text to analyze for readability
        
    Returns:
        JSON string containing readability analysis and improvement suggestions
    """
    # Basic text analysis
    words = content.split()
    sentences = [s.strip() for s in content.split('.') if s.strip()]
    syllables = sum(max(1, len([c for c in word if c.lower() in 'aeiouy'])) for word in words)
    
    word_count = len(words)
    sentence_count = len(sentences)
    avg_sentence_length = word_count / max(sentence_count, 1)
    avg_syllables_per_word = syllables / max(word_count, 1)
    
    # Calculate Flesch-Kincaid Reading Ease (simplified)
    flesch_score = 206.835 - (1.015 * avg_sentence_length) - (84.6 * avg_syllables_per_word)
    flesch_score = max(0, min(100, flesch_score))
    
    # Determine reading level
    if flesch_score >= 90:
        reading_level = "Very Easy (5th grade)"
        grade = "A+"
    elif flesch_score >= 80:
        reading_level = "Easy (6th grade)"
        grade = "A"
    elif flesch_score >= 70:
        reading_level = "Fairly Easy (7th grade)"
        grade = "B+"
    elif flesch_score >= 60:
        reading_level = "Standard (8th-9th grade)"
        grade = "B"
    elif flesch_score >= 50:
        reading_level = "Fairly Difficult (10th-12th grade)"
        grade = "B-"
    elif flesch_score >= 30:
        reading_level = "Difficult (College level)"
        grade = "C"
    else:
        reading_level = "Very Difficult (Graduate level)"
        grade = "C-"
    
    # Analyze complex words (3+ syllables)
    complex_words = [word for word in words if max(1, len([c for c in word if c.lower() in 'aeiouy'])) >= 3]
    complex_words_percentage = (len(complex_words) / max(word_count, 1)) * 100
    
    # Generate improvement suggestions
    improvement_suggestions = []
    if avg_sentence_length > 20:
        improvement_suggestions.append("Use shorter sentences (aim for 15-20 words)")
    if complex_words_percentage > 15:
        improvement_suggestions.append("Simplify complex vocabulary where possible")
    if flesch_score < 60:
        improvement_suggestions.append("Break down complex concepts into simpler terms")
    if sentence_count < word_count / 25:
        improvement_suggestions.append("Add more sentence variety")
    
    if not improvement_suggestions:
        improvement_suggestions.append("Readability is already at a good level")
    
    result = {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "average_sentence_length": round(avg_sentence_length, 1),
        "average_syllables_per_word": round(avg_syllables_per_word, 1),
        "flesch_kincaid_score": round(flesch_score, 1),
        "reading_level": reading_level,
        "readability_grade": grade,
        "complex_words_count": len(complex_words),
        "complex_words_percentage": round(complex_words_percentage, 1),
        "improvement_suggestions": improvement_suggestions,
        "target_audience_match": "Good" if 50 <= flesch_score <= 70 else "Needs Adjustment",
        "estimated_reading_time": f"{max(1, word_count // 200)} minutes"
    }
    
    return json.dumps(result, indent=2)

# ==================== AGENT DEFINITIONS ====================

# LLM Configuration
llm = LLM(
    model="openai/doubao-1-5-vision-pro-32k-250115",
    temperature=0.7,
)

# Research Specialist Agent
research_specialist = Agent(
    role='Senior Content Researcher',
    goal='Conduct comprehensive research on topics and gather authoritative sources for content creation',
    backstory='You are an experienced content researcher with expertise in finding trending topics, verifying facts, and gathering compelling statistics. You excel at identifying content opportunities and ensuring information accuracy.',
    tools=[search_trending_topics, fact_check_content, gather_statistics],
    llm=llm,
    verbose=True
)

# Content Strategist Agent
content_strategist = Agent(
    role='Content Strategy Expert',
    goal='Create content strategy, outline, and SEO optimization plan based on research insights',
    backstory='You are a strategic content planner with deep understanding of audience psychology and SEO best practices. You excel at transforming research into actionable content strategies and comprehensive outlines.',
    tools=[analyze_target_audience, generate_seo_keywords, create_content_outline],
    llm=llm,
    verbose=True
)

# Content Writer Agent
content_writer = Agent(
    role='Professional Content Writer',
    goal='Create engaging, high-quality blog content based on strategy and research',
    backstory='You are a skilled content writer with expertise in creating compelling narratives and engaging copy. You excel at crafting introductions that hook readers, creating effective calls-to-action, and formatting content for maximum impact.',
    tools=[write_engaging_intro, create_call_to_action, format_content],
    llm=llm,
    verbose=True
)

# Quality Assurance Editor Agent
quality_assurance_editor = Agent(
    role='Editorial Quality Expert',
    goal='Review, edit, and ensure content quality and consistency through comprehensive analysis',
    backstory='You are a meticulous editor with a keen eye for detail and quality. You excel at grammar checking, validating content flow, and ensuring readability standards are met for optimal user experience.',
    tools=[check_grammar_style, validate_content_flow, calculate_readability_score],
    llm=llm,
    verbose=True
)

# ==================== TASK DEFINITIONS ====================

def create_blog_content_tasks(topic: str):
    """Create comprehensive blog content creation tasks for all agents"""
    
    # Task 1: Research and Discovery
    research_task = Task(
        description=f"""
        Conduct comprehensive research on the topic: "{topic}"
        
        Your research should include:
        1. Use search_trending_topics to identify trending keywords and content opportunities
        2. Use gather_statistics to collect relevant data and supporting evidence
        3. Use fact_check_content to verify any claims or information you find
        
        Deliver a comprehensive research report that includes:
        - Trending keywords and search opportunities
        - Key statistics and data points with sources
        - Fact-checked information and credibility assessment
        - Content opportunities and angles to explore
        - Target audience insights for this topic
        """,
        expected_output="A detailed research report with trending insights, verified statistics, and content opportunities",
        agent=research_specialist
    )
    
    # Task 2: Strategy and Planning
    strategy_task = Task(
        description=f"""
        Based on the research findings, develop a comprehensive content strategy for "{topic}"
        
        Your strategy should include:
        1. Use analyze_target_audience to understand the audience for this topic
        2. Use generate_seo_keywords to create SEO optimization plan
        3. Use create_content_outline to structure the content based on audience and SEO insights
        
        Deliver a complete content strategy that includes:
        - Target audience analysis and preferences
        - SEO keyword strategy and optimization plan
        - Detailed content outline with sections and word counts
        - Content tone and style recommendations
        - Engagement and conversion strategy
        """,
        expected_output="A comprehensive content strategy with audience analysis, SEO plan, and detailed outline",
        agent=content_strategist,
        context=[research_task]
    )
    
    # Task 3: Content Creation
    writing_task = Task(
        description=f"""
        Create high-quality blog content for "{topic}" based on the research and strategy
        
        Your content creation should include:
        1. Use write_engaging_intro to create a compelling opening
        2. Use create_call_to_action to design effective CTAs
        3. Use format_content to ensure proper structure and readability
        
        Create a complete blog article that includes:
        - Engaging introduction that hooks the reader
        - Well-structured main content following the outline
        - Relevant examples, statistics, and practical insights
        - Strategic calls-to-action throughout the content
        - Proper formatting for web readability
        - SEO-optimized content with natural keyword integration
        
        Target length: 1200-1500 words
        """,
        expected_output="A complete, well-written blog article with engaging content and proper formatting",
        agent=content_writer,
        context=[research_task, strategy_task]
    )
    
    # Task 4: Quality Assurance and Review
    quality_task = Task(
        description=f"""
        Conduct comprehensive quality assurance on the blog content for "{topic}"
        
        Your quality review should include:
        1. Use check_grammar_style to analyze grammar and writing quality
        2. Use validate_content_flow to ensure logical progression
        3. Use calculate_readability_score to assess accessibility
        
        Provide a detailed quality assessment that includes:
        - Grammar and style analysis with specific recommendations
        - Content flow validation and structural feedback
        - Readability score and accessibility assessment
        - Overall quality rating and improvement suggestions
        - Final approval or revision recommendations
        
        If the content scores below 8.0 in any major area, provide specific improvement recommendations.
        """,
        expected_output="A comprehensive quality assessment with scores, analysis, and improvement recommendations",
        agent=quality_assurance_editor,
        context=[writing_task]
    )
    
    return [research_task, strategy_task, writing_task, quality_task]

# ==================== MAIN EXECUTION FUNCTION ====================

def main():
    """Main function: Execute the content creation multi-agent system"""
    print("🚀 Starting Content Creation Multi-Agent System...")
    print("=" * 70)
    
    # Example topic for content creation
    topic = "Artificial Intelligence in Modern Business"
    print(f"📝 Content Topic: {topic}")
    print("=" * 70)
    
    # Create all tasks
    tasks = create_blog_content_tasks(topic)
    
    # Create Crew with all agents working together in a single execution
    crew = Crew(
        agents=[research_specialist, content_strategist, content_writer, quality_assurance_editor],
        tasks=tasks,
        verbose=True
    )
    
    # Execute the complete content creation pipeline
    print("🔄 Starting content creation pipeline...")
    print("Pipeline: Research → Strategy → Writing → Quality Assurance")
    print("=" * 70)
    
    start_time = time.time()
    result = crew.kickoff()
    end_time = time.time()
    
    print("=" * 70)
    print("✅ Content Creation Pipeline Complete!")
    print(f"⏱️  Total execution time: {end_time - start_time:.2f} seconds")
    print("=" * 70)
    print("📄 Final Content Output:")
    print(result)
    print("=" * 70)

if __name__ == "__main__":
    main()