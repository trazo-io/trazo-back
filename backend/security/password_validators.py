"""
Enhanced Password Validators for Trazo
Implements OWASP 2025 password security guidelines
"""

import hashlib
import logging
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

import requests

logger = logging.getLogger(__name__)


class EnhancedMinimumLengthValidator:
    """
    SECURITY: Enhanced minimum length validator with entropy considerations
    """

    def __init__(self, min_length=12):
        self.min_length = min_length

    def validate(self, password, user=None):
        if len(password) < self.min_length:
            raise ValidationError(
                _("This password must contain at least %(min_length)d characters."),
                code="password_too_short",
                params={"min_length": self.min_length},
            )

    def get_help_text(self):
        return _("Your password must contain at least %(min_length)d characters." % {"min_length": self.min_length})


class PasswordComplexityValidator:
    """
    SECURITY: Enforces password complexity requirements
    Requires uppercase, lowercase, numbers, and special characters
    """

    def __init__(self, min_uppercase=1, min_lowercase=1, min_digits=1, min_special=1):
        self.min_uppercase = min_uppercase
        self.min_lowercase = min_lowercase
        self.min_digits = min_digits
        self.min_special = min_special

    def validate(self, password, user=None):
        errors = []

        # Check uppercase letters
        if len(re.findall(r"[A-Z]", password)) < self.min_uppercase:
            errors.append(f"at least {self.min_uppercase} uppercase letter(s)")

        # Check lowercase letters
        if len(re.findall(r"[a-z]", password)) < self.min_lowercase:
            errors.append(f"at least {self.min_lowercase} lowercase letter(s)")

        # Check digits
        if len(re.findall(r"\d", password)) < self.min_digits:
            errors.append(f"at least {self.min_digits} digit(s)")

        # Check special characters
        if len(re.findall(r'[!@#$%^&*(),.?":{}|<>]', password)) < self.min_special:
            errors.append(f"at least {self.min_special} special character(s)")

        if errors:
            raise ValidationError(
                _("Password must contain %(requirements)s."),
                code="password_complexity",
                params={"requirements": ", ".join(errors)},
            )

    def get_help_text(self):
        return _(
            "Your password must contain at least %(min_uppercase)d uppercase letter, "
            "%(min_lowercase)d lowercase letter, %(min_digits)d digit, "
            "and %(min_special)d special character."
            % {
                "min_uppercase": self.min_uppercase,
                "min_lowercase": self.min_lowercase,
                "min_digits": self.min_digits,
                "min_special": self.min_special,
            }
        )


class PasswordEntropyValidator:
    """
    SECURITY: Validates password entropy to prevent predictable passwords
    """

    def __init__(self, min_entropy=50):
        self.min_entropy = min_entropy

    def calculate_entropy(self, password):
        """
        Calculate password entropy based on character set and length
        """
        charset_size = 0

        # Check for different character types
        if re.search(r"[a-z]", password):
            charset_size += 26
        if re.search(r"[A-Z]", password):
            charset_size += 26
        if re.search(r"\d", password):
            charset_size += 10
        if re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            charset_size += 18
        if re.search(r"[\s]", password):
            charset_size += 1

        # Additional characters (extended ASCII)
        if re.search(r'[^\w\s!@#$%^&*(),.?":{}|<>]', password):
            charset_size += 20

        # Calculate entropy: H = L * log2(N)
        # Where L = length, N = charset size
        import math

        if charset_size > 0:
            entropy = len(password) * math.log2(charset_size)
            return entropy
        return 0

    def validate(self, password, user=None):
        entropy = self.calculate_entropy(password)
        if entropy < self.min_entropy:
            raise ValidationError(
                _(
                    "Password is too simple. "
                    "Try making it longer or adding different character types."
                ),
                code="password_entropy_low",
                params={"entropy": entropy, "min_entropy": self.min_entropy},
            )

    def get_help_text(self):
        return _(
            "Your password must be complex enough — "
            "use a mix of letters, numbers, and special characters."
        )


class BreachedPasswordValidator:
    """
    SECURITY: Checks passwords against known breach databases
    Uses SHA-1 hash prefix for privacy (HaveIBeenPwned API)
    """

    def __init__(self, enabled=True, timeout=5):
        self.enabled = enabled and not settings.DEBUG  # Disable in development
        self.timeout = timeout

    def validate(self, password, user=None):
        if not self.enabled:
            return

        try:
            # Hash the password with SHA-1
            sha1_hash = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
            prefix = sha1_hash[:5]
            suffix = sha1_hash[5:]

            # Query HaveIBeenPwned API with k-anonymity
            url = f"https://api.pwnedpasswords.com/range/{prefix}"
            response = requests.get(url, timeout=self.timeout)

            if response.status_code == 200:
                # Check if our password hash appears in the results
                for line in response.text.splitlines():
                    hash_suffix, count = line.split(":")
                    if hash_suffix == suffix:
                        raise ValidationError(
                            _(
                                "This password has been found in data breaches "
                                "and is not secure. Please choose a different password."
                            ),
                            code="password_breached",
                        )

        except requests.RequestException:
            # If API is unavailable, log but don't block user
            logger.warning("Could not check password against breach database")
        except Exception as e:
            logger.error(f"Error checking breached passwords: {str(e)}")

    def get_help_text(self):
        if self.enabled:
            return _("Your password will be checked against known data breaches.")
        return _("Password breach checking is disabled in development.")


class NoPersonalInformationValidator:
    """
    SECURITY: Enhanced validator to prevent personal information in passwords
    """

    def validate(self, password, user=None):
        if not user:
            return

        # Convert password to lowercase for comparison
        password_lower = password.lower()

        # Check against user attributes
        if user.email:
            email_parts = user.email.lower().split("@")
            username = email_parts[0]
            domain = email_parts[1].split(".")[0]

            if len(username) >= 3 and username in password_lower:
                raise ValidationError(
                    _("Password cannot contain your email address."),
                    code="password_contains_email",
                )

            if len(domain) >= 3 and domain in password_lower:
                raise ValidationError(
                    _("Password cannot contain your email domain."),
                    code="password_contains_domain",
                )

        # Check against name fields
        if hasattr(user, "first_name") and user.first_name:
            if len(user.first_name) >= 3 and user.first_name.lower() in password_lower:
                raise ValidationError(
                    _("Password cannot contain your first name."),
                    code="password_contains_first_name",
                )

        if hasattr(user, "last_name") and user.last_name:
            if len(user.last_name) >= 3 and user.last_name.lower() in password_lower:
                raise ValidationError(
                    _("Password cannot contain your last name."),
                    code="password_contains_last_name",
                )

        # Check against common personal patterns
        personal_patterns = [
            r"\b(password|pass|123|abc|qwerty)\b",
            r"\b(admin|user|guest|test)\b",
            r"\b(trazo|farm|agriculture|carbon)\b",  # Application-specific terms
        ]

        for pattern in personal_patterns:
            if re.search(pattern, password_lower):
                raise ValidationError(
                    _("Password cannot contain common words or predictable patterns."),
                    code="password_contains_common_words",
                )

    def get_help_text(self):
        return _("Your password cannot contain personal information, " "common words, or predictable patterns.")


class NoSequentialCharactersValidator:
    """
    SECURITY: Prevents sequential characters and keyboard patterns
    """

    def __init__(self, max_sequential=3):
        self.max_sequential = max_sequential

    def validate(self, password, user=None):
        # Check for sequential numbers
        for i in range(len(password) - self.max_sequential + 1):
            substr = password[i : i + self.max_sequential]
            if substr.isdigit():
                if self.is_sequential_numbers(substr):
                    raise ValidationError(
                        _("Password cannot contain sequential numbers."),
                        code="password_sequential_numbers",
                    )

        # Check for sequential letters
        for i in range(len(password) - self.max_sequential + 1):
            substr = password[i : i + self.max_sequential].lower()
            if substr.isalpha():
                if self.is_sequential_letters(substr):
                    raise ValidationError(
                        _("Password cannot contain sequential letters."),
                        code="password_sequential_letters",
                    )

        # Check for keyboard patterns
        keyboard_patterns = ["qwerty", "asdf", "zxcv", "1234", "abcd", "qwertyuiop", "asdfghjkl", "zxcvbnm"]

        password_lower = password.lower()
        for pattern in keyboard_patterns:
            if pattern in password_lower or pattern[::-1] in password_lower:
                raise ValidationError(
                    _("Password cannot contain keyboard patterns."),
                    code="password_keyboard_pattern",
                )

    def is_sequential_numbers(self, substr):
        """Check if string contains sequential numbers"""
        for i in range(len(substr) - 1):
            if int(substr[i + 1]) != int(substr[i]) + 1:
                return False
        return True

    def is_sequential_letters(self, substr):
        """Check if string contains sequential letters"""
        for i in range(len(substr) - 1):
            if ord(substr[i + 1]) != ord(substr[i]) + 1:
                return False
        return True

    def get_help_text(self):
        return _("Your password cannot contain sequential characters " "or keyboard patterns.")
