"""Shared fake site definition so GA and Clarity mock data join up in the combined view."""
from __future__ import annotations

from dataclasses import dataclass

MOCK_DOMAIN = "https://www.example-store.com"

# (account_id, account_name, property_id, property_name, traffic scale, has a Clarity project)
MOCK_PROPERTIES: list[tuple[str, str, str, str, float, bool]] = [
    ("900001", "Example Store", "100000001", "Example Store", 1.0, True),
    ("900001", "Example Store", "100000002", "Example Store — Staging", 0.04, False),
    ("900002", "Travel Blog", "100000003", "Travel Blog", 0.32, True),
]


def mock_scale(property_id: str) -> float:
    """Traffic multiplier per mock property; unknown IDs get a stable pseudo-random scale."""
    for *_, pid, _, scale, _ in MOCK_PROPERTIES:
        if pid == property_id:
            return scale
    return 0.2 + (sum(map(ord, property_id or "x")) % 60) / 100


@dataclass(frozen=True)
class MockPage:
    path: str
    title: str
    weight: float  # share of page views
    frustration: float = 1.0  # multiplier for rage/dead clicks in Clarity
    scroll: float = 55.0  # typical scroll depth %


MOCK_PAGES: list[MockPage] = [
    MockPage("/", "Example Store — Home", 0.22, 0.8, 48),
    MockPage("/pricing", "Pricing & Plans", 0.09, 4.2, 38),
    MockPage("/products", "All Products", 0.08, 1.1, 62),
    MockPage("/blog", "Blog", 0.06, 0.6, 58),
    MockPage("/checkout", "Checkout", 0.055, 3.6, 71),
    MockPage("/products/smart-watch", "Smart Watch S2", 0.05, 1.3, 66),
    MockPage("/products/wireless-earbuds", "Wireless Earbuds Pro", 0.045, 1.0, 64),
    MockPage("/cart", "Your Cart", 0.04, 2.1, 74),
    MockPage("/signup", "Create an account", 0.035, 1.8, 80),
    MockPage("/login", "Sign in", 0.032, 1.2, 85),
    MockPage("/blog/how-to-choose-a-smart-watch", "How to choose a smart watch", 0.03, 0.4, 45),
    MockPage("/about", "About us", 0.025, 0.5, 52),
    MockPage("/contact", "Contact", 0.022, 2.6, 77),
    MockPage("/products/fitness-band", "Fitness Band Lite", 0.02, 0.9, 61),
    MockPage("/blog/battery-life-tips", "10 battery life tips", 0.019, 0.3, 42),
    MockPage("/support", "Help Centre", 0.018, 1.6, 57),
    MockPage("/support/shipping", "Shipping & delivery", 0.016, 1.0, 68),
    MockPage("/support/returns", "Returns policy", 0.014, 1.4, 63),
    MockPage("/careers", "Careers", 0.012, 0.5, 49),
    MockPage("/account/orders", "My orders", 0.011, 2.3, 70),
    MockPage("/products/charging-dock", "Charging Dock", 0.01, 0.8, 59),
    MockPage("/blog/release-notes-2026", "Release notes 2026", 0.009, 0.4, 36),
    MockPage("/compare", "Compare devices", 0.008, 2.9, 41),
    MockPage("/gift-cards", "Gift cards", 0.007, 0.7, 60),
]

CHANNELS = [
    ("Organic Search", 0.41), ("Direct", 0.22), ("Organic Social", 0.11), ("Referral", 0.09),
    ("Paid Search", 0.08), ("Email", 0.05), ("Paid Social", 0.025), ("Unassigned", 0.015),
]

SOURCES = [
    ("google", "organic", 0.36), ("(direct)", "(none)", 0.22), ("bing", "organic", 0.04), ("instagram.com", "referral", 0.05),
    ("facebook.com", "referral", 0.04), ("google", "cpc", 0.08), ("newsletter", "email", 0.05), ("t.co", "referral", 0.02),
    ("linkedin.com", "referral", 0.018), ("duckduckgo", "organic", 0.01), ("reddit.com", "referral", 0.015),
    ("producthunt.com", "referral", 0.012), ("meta", "paid_social", 0.025), ("chatgpt.com", "referral", 0.02),
    ("youtube.com", "referral", 0.015),
]

COUNTRIES = [
    ("India", 0.46, ["Bengaluru", "Mumbai", "Delhi", "Hyderabad", "Chennai", "Pune", "Kolkata"]),
    ("United States", 0.18, ["New York", "San Francisco", "Austin", "Seattle"]),
    ("United Kingdom", 0.07, ["London", "Manchester"]),
    ("Germany", 0.05, ["Berlin", "Munich"]),
    ("Canada", 0.04, ["Toronto", "Vancouver"]),
    ("Australia", 0.035, ["Sydney", "Melbourne"]),
    ("Singapore", 0.03, ["Singapore"]),
    ("United Arab Emirates", 0.025, ["Dubai"]),
    ("France", 0.02, ["Paris"]),
    ("Netherlands", 0.015, ["Amsterdam"]),
    ("Brazil", 0.012, ["São Paulo"]),
    ("Japan", 0.01, ["Tokyo"]),
]

DEVICES = [("mobile", 0.61), ("desktop", 0.35), ("tablet", 0.04)]
BROWSERS = [("Chrome", 0.63), ("Safari", 0.21), ("Edge", 0.06), ("Samsung Internet", 0.04), ("Firefox", 0.035), ("Opera", 0.015)]
OSES = [("Android", 0.42), ("iOS", 0.22), ("Windows", 0.21), ("Macintosh", 0.11), ("Linux", 0.03), ("Chrome OS", 0.01)]

EVENTS = [
    ("page_view", 2.4), ("user_engagement", 1.6), ("session_start", 1.0), ("scroll", 0.9), ("first_visit", 0.62),
    ("click", 0.45), ("view_item", 0.38), ("add_to_cart", 0.07), ("begin_checkout", 0.045), ("form_start", 0.04),
    ("sign_up", 0.022), ("generate_lead", 0.018), ("purchase", 0.016), ("file_download", 0.012), ("video_start", 0.011),
]
