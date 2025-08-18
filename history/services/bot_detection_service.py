"""
Bot Detection Service (2025 Standards)
Modern bot detection with machine learning patterns and behavioral analysis
"""

import re
import time
from typing import Dict, List, Optional, Tuple
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta


class BotDetectionService:
    """Modern bot detection following 2025 security standards"""
    
    # Known bot user agent patterns (updated for 2025)
    BOT_USER_AGENT_PATTERNS = [
        # Search engine bots
        r'googlebot|bingbot|slurp|duckduckbot|baiduspider|yandexbot|sogou|exabot',
        r'facebookexternalhit|twitterbot|linkedinbot|pinterest|whatsapp|telegram',
        
        # SEO and monitoring bots
        r'ahrefsbot|semrushbot|mj12bot|dotbot|rogerbot|screaming frog',
        r'uptimerobot|pingdom|gtmetrix|webpagetest|lighthouse',
        
        # Scraping and automation tools
        r'scrapy|selenium|phantomjs|headlesschrome|playwright|puppeteer',
        r'curl|wget|httpie|postman|python-requests|node-fetch',
        
        # Security scanners
        r'nmap|nikto|sqlmap|nessus|openvas|burp|zap|nuclei',
        
        # Generic bot indicators
        r'bot|crawler|spider|scraper|automated|robot|harvester',
        r'monitor|checker|validator|parser|indexer|fetcher'
    ]
    
    # Suspicious request patterns
    SUSPICIOUS_PATTERNS = {
        'too_fast': 0.5,        # Requests faster than 500ms
        'no_referrer': 0.2,     # No referrer header
        'suspicious_ua': 0.8,   # Bot-like user agent
        'no_js_headers': 0.3,   # Missing typical browser headers
        'rapid_succession': 0.6, # Multiple rapid requests
        'invalid_encoding': 0.4, # Unusual encoding patterns
    }
    
    @staticmethod
    def calculate_bot_score(request, scan_data: Optional[Dict] = None) -> float:
        """
        Calculate probability that request is from a bot (0.0-1.0)
        
        Args:
            request: Django request object
            scan_data: Additional scan data for analysis
            
        Returns:
            Bot score between 0.0 (definitely human) and 1.0 (definitely bot)
        """
        score = 0.0
        max_score = 1.0
        
        # User agent analysis (40% weight)
        ua_score = BotDetectionService._analyze_user_agent(request)
        score += ua_score * 0.4
        
        # Request timing analysis (20% weight)
        timing_score = BotDetectionService._analyze_request_timing(request)
        score += timing_score * 0.2
        
        # Header analysis (20% weight)
        header_score = BotDetectionService._analyze_headers(request)
        score += header_score * 0.2
        
        # Content analysis (20% weight)
        if scan_data:
            content_score = BotDetectionService._analyze_content(scan_data)
            score += content_score * 0.2
        
        return min(score, max_score)
    
    @staticmethod
    def _analyze_user_agent(request) -> float:
        """
        Analyze user agent for bot patterns
        Returns score between 0.0 and 1.0
        """
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        
        if not user_agent:
            return 0.8  # No user agent is highly suspicious
        
        # Check against known bot patterns
        for pattern in BotDetectionService.BOT_USER_AGENT_PATTERNS:
            if re.search(pattern, user_agent, re.IGNORECASE):
                return 0.9  # High probability of bot
        
        # Check for suspicious characteristics
        score = 0.0
        
        # Very short user agent
        if len(user_agent) < 20:
            score += 0.3
        
        # Very long user agent (some bots use extremely long UAs)
        if len(user_agent) > 500:
            score += 0.2
        
        # Missing browser version info
        if not re.search(r'\d+\.\d+', user_agent):
            score += 0.2
        
        # Unusual format
        if not any(browser in user_agent for browser in ['chrome', 'firefox', 'safari', 'edge', 'opera']):
            score += 0.3
        
        return min(score, 1.0)
    
    @staticmethod
    def _analyze_request_timing(request) -> float:
        """
        Analyze request timing patterns for bot behavior
        """
        client_ip = BotDetectionService._get_client_ip(request)
        if not client_ip:
            return 0.0
        
        # Check cache for recent requests from same IP
        cache_key = f"bot_detection_timing:{client_ip}"
        request_times = cache.get(cache_key, [])
        
        current_time = time.time()
        
        # Add current request time
        request_times.append(current_time)
        
        # Keep only requests from last 5 minutes
        recent_requests = [t for t in request_times if current_time - t < 300]
        
        # Update cache
        cache.set(cache_key, recent_requests, 300)  # 5 minutes
        
        score = 0.0
        
        # Too many requests in short time
        if len(recent_requests) > 20:  # More than 20 requests in 5 minutes
            score += 0.8
        elif len(recent_requests) > 10:  # More than 10 requests in 5 minutes
            score += 0.5
        elif len(recent_requests) > 5:   # More than 5 requests in 5 minutes
            score += 0.3
        
        # Check for extremely rapid requests
        if len(recent_requests) >= 2:
            time_diff = recent_requests[-1] - recent_requests[-2]
            if time_diff < 1:  # Less than 1 second between requests
                score += 0.6
            elif time_diff < 3:  # Less than 3 seconds between requests
                score += 0.3
        
        return min(score, 1.0)
    
    @staticmethod
    def _analyze_headers(request) -> float:
        """
        Analyze HTTP headers for bot patterns
        """
        score = 0.0
        
        # Check for missing typical browser headers
        expected_headers = [
            'HTTP_ACCEPT',
            'HTTP_ACCEPT_LANGUAGE',
            'HTTP_ACCEPT_ENCODING',
            'HTTP_CONNECTION'
        ]
        
        missing_headers = sum(1 for header in expected_headers if not request.META.get(header))
        score += (missing_headers / len(expected_headers)) * 0.4
        
        # Check for suspicious header values
        accept_header = request.META.get('HTTP_ACCEPT', '')
        if accept_header == '*/*':  # Very generic accept header
            score += 0.2
        
        # Check for automation tool headers
        automation_headers = [
            'HTTP_X_REQUESTED_WITH',
            'HTTP_X_AUTOMATION',
            'HTTP_X_ROBOT',
            'HTTP_X_CRAWLER'
        ]
        
        if any(request.META.get(header) for header in automation_headers):
            score += 0.5
        
        # Check referrer
        referrer = request.META.get('HTTP_REFERER', '')
        if not referrer and request.method == 'POST':
            score += 0.3  # POST without referrer is suspicious
        
        return min(score, 1.0)
    
    @staticmethod
    def _analyze_content(scan_data: Dict) -> float:
        """
        Analyze scan content for bot-generated patterns
        """
        score = 0.0
        
        comment = scan_data.get('comment', '')
        
        if comment:
            # Check for spam patterns
            spam_score = BotDetectionService._detect_spam_content(comment)
            score += spam_score * 0.7
            
            # Check for generated content patterns
            if BotDetectionService._is_generated_content(comment):
                score += 0.3
        
        # Check for suspicious form data patterns
        if BotDetectionService._has_suspicious_form_data(scan_data):
            score += 0.4
        
        return min(score, 1.0)
    
    @staticmethod
    def _detect_spam_content(text: str) -> float:
        """
        Detect spam patterns in text content
        """
        if not text or len(text.strip()) == 0:
            return 0.0
        
        text_lower = text.lower()
        score = 0.0
        
        # Common spam patterns
        spam_patterns = [
            r'(https?://|www\.)\S+',  # URLs
            r'(buy|cheap|free|discount|offer|deal)\s+(now|today|here)',
            r'(click|visit|check)\s+(here|now|this)',
            r'(earn|make)\s+\$?\d+',
            r'(viagra|cialis|pharmacy|pills)',
            r'(casino|poker|betting|gambling)',
        ]
        
        for pattern in spam_patterns:
            if re.search(pattern, text_lower):
                score += 0.3
        
        # Repetitive content
        words = text_lower.split()
        if len(words) > 5:
            unique_words = set(words)
            repetition_ratio = len(words) / len(unique_words)
            if repetition_ratio > 3:  # Too much repetition
                score += 0.4
        
        # All caps (spam indicator)
        caps_ratio = sum(1 for c in text if c.isupper()) / len(text)
        if caps_ratio > 0.7:
            score += 0.3
        
        return min(score, 1.0)
    
    @staticmethod
    def _is_generated_content(text: str) -> bool:
        """
        Check if content appears to be AI/bot generated
        """
        # Simple heuristics for generated content
        generic_phrases = [
            'as an ai',
            'i am a bot',
            'automated message',
            'this is a test',
            'lorem ipsum',
            'sample text',
            'default comment'
        ]
        
        text_lower = text.lower()
        return any(phrase in text_lower for phrase in generic_phrases)
    
    @staticmethod
    def _has_suspicious_form_data(scan_data: Dict) -> bool:
        """
        Check for suspicious form submission patterns
        """
        # Very rapid form submission (would be passed from frontend)
        submission_time = scan_data.get('form_submission_time', 0)
        if submission_time > 0 and submission_time < 2:  # Less than 2 seconds
            return True
        
        # Honeypot field filled (would be added by frontend)
        honeypot = scan_data.get('website', '')  # Common honeypot field name
        if honeypot:
            return True
        
        return False
    
    @staticmethod
    def _get_client_ip(request) -> Optional[str]:
        """
        Get client IP address for rate limiting
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        
        return ip
    
    @staticmethod
    def is_verified_human(request, scan_data: Optional[Dict] = None) -> bool:
        """
        Determine if request is from a verified human user
        
        Args:
            request: Django request object
            scan_data: Additional scan data
            
        Returns:
            True if verified human, False otherwise
        """
        bot_score = BotDetectionService.calculate_bot_score(request, scan_data)
        
        # Conservative threshold - only mark as human if bot score is very low
        return bot_score < 0.2
    
    @staticmethod
    def should_block_request(request, scan_data: Optional[Dict] = None) -> Tuple[bool, str]:
        """
        Determine if request should be blocked
        
        Returns:
            Tuple of (should_block: bool, reason: str)
        """
        bot_score = BotDetectionService.calculate_bot_score(request, scan_data)
        
        # Block if bot score is very high
        if bot_score >= 0.8:
            return True, "High bot probability"
        
        # Check for rate limiting
        client_ip = BotDetectionService._get_client_ip(request)
        if client_ip:
            # Check if IP is making too many requests
            cache_key = f"rate_limit:{client_ip}"
            request_count = cache.get(cache_key, 0)
            
            if request_count > 30:  # More than 30 requests per minute
                return True, "Rate limit exceeded"
            
            # Increment counter
            cache.set(cache_key, request_count + 1, 60)  # 1 minute window
        
        return False, ""
    
    @staticmethod
    def get_bot_detection_stats(days: int = 7) -> Dict:
        """
        Get bot detection statistics for monitoring
        """
        from ..models import HistoryScan
        
        start_date = timezone.now() - timedelta(days=days)
        
        scans = HistoryScan.objects.filter(date__gte=start_date)
        total_scans = scans.count()
        
        if total_scans == 0:
            return {
                'total_scans': 0,
                'human_scans': 0,
                'bot_scans': 0,
                'bot_percentage': 0,
                'avg_bot_score': 0
            }
        
        # Count scans by bot score thresholds
        high_confidence_humans = scans.filter(bot_score__lt=0.2).count()
        likely_bots = scans.filter(bot_score__gte=0.7).count()
        
        # Calculate averages
        total_bot_score = sum(scan.bot_score for scan in scans)
        avg_bot_score = total_bot_score / total_scans
        
        bot_percentage = (likely_bots / total_scans) * 100
        
        return {
            'total_scans': total_scans,
            'human_scans': high_confidence_humans,
            'bot_scans': likely_bots,
            'bot_percentage': round(bot_percentage, 2),
            'avg_bot_score': round(avg_bot_score, 3),
            'period_days': days
        }