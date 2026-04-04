import re


DISPLAY_TYPE_MAP = {
    "CRLMC": "CRL.M.C.",
    "WPC": "W.P.(C)",
    "CSCOMM": "CS(COMM)",
    "FAOOS": "FAO(OS)",
    "CRLA": "CRL.A.",
    "CMM": "CM(M)",
    "CMAPPL": "CM APPL",  # Add normalized form
}

def normalize_case_id(case_number: str) -> str:
    """
    Normalize a case number to a strict canonical format: TYPE-NUMBER-YEAR.
    Example: "CRL.M.C. 8148/2025" -> "CRLMC-8148-2025"
    
    Returns None if the input cannot be normalized to this format.
    """
    if not case_number:
        return None
        
    # Uppercase everything
    raw = case_number.upper()
    raw = re.sub(r"\bSLASH\b", "/", raw)
    
    # Regex to extract parts: Type, Number, Year
    # Supports: 
    # - CRL.M.C. 8148/2025
    # - CRLMC-8148-2025
    # - CRL MC 2456 of 2024
    # Look for Type (letters/dots/parens/hyphens), followed by Number, followed by Year
    # We allow 'OF', '-', '/' between number and year
    pattern = r'(?<![a-zA-Z])([A-Z][A-Z\.\(\)\s-]*?)\s*[-/]?\s*(\d+)\s*(?:[-/]|OF)\s*(\d{4})'
    
    match = re.search(pattern, raw)
    if not match:
        return None
        
    raw_type, number, year = match.groups()
    
    # Clean the type: remove dots, spaces, parens, hyphens
    clean_type = re.sub(r'[^A-Z0-9]', '', raw_type)
    
    # Strip common prefixes that might have been captured as part of the type
    # e.g. "ADDCASECRLMC" -> "CRLMC"
    PREFIXES = ["ADD", "CASE", "TRACK", "CHECK", "STATUS", "OF", "FOR", "THE", "IN", "MATTER", "MY", "WITH", "AND"]
    
    # We loop until no prefix matches
    while True:
        found = False
        for prefix in PREFIXES:
            if clean_type.startswith(prefix) and len(clean_type) > len(prefix):
                clean_type = clean_type[len(prefix):]
                found = True
                break # Restart loop
        if not found:
            break
            
    if not clean_type:
        return None # Must have a type
        
    # Construct canonical ID
    return f"{clean_type}-{number}-{year}"

def parse_case_number(text: str) -> str:
    """
    Extract the first valid case number from text.
    Returns the original string if found, or None.
    """
    canonical = normalize_case_id(text)
    if not canonical:
        return None

    try:
        raw_type, number, year = canonical.split("-", 2)
    except ValueError:
        return None

    display_type = DISPLAY_TYPE_MAP.get(raw_type)
    if not display_type:
        # Some free-text inputs may prepend words before the actual case type.
        for canonical_type, display in DISPLAY_TYPE_MAP.items():
            if raw_type.endswith(canonical_type):
                display_type = display
                break
    if not display_type:
        display_type = raw_type
    return f"{display_type} {number}/{year}"

def extract_all_case_numbers(text: str) -> list[str]:
    """
    Extract ALL valid case numbers from a text block.
    Handles multi-line and broken layouts:
    - CM APPL. 11440/2026
    - CMAPPL 11440 / 2026  
    - CM APPL 11440 / 2026 (split)
    Returns list of original case strings found.
    """
    if not text:
        return []
    
    import logging
    logger = logging.getLogger(__name__)
    
    # Normalize for matching
    normalized = text.upper()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"CM\s*APPL\.?", "CMAPPL", normalized)
    
    candidates = []
    
    # PATTERN 1: Normalized forms like "CMAPPL 11440/2026" or "CMAPPL 11440 / 2026"
    # Capture with separator preserved
    pattern1 = r'(CMAPPL|CRLMC|WPC|CSCOMM|FAOOS|CRLA|CMM)\s+(\d+)\s*([-/]|OF)\s*(\d{4})'
    matches1 = re.finditer(pattern1, normalized, re.IGNORECASE)
    for match in matches1:
        case_type = match.group(1).strip()
        number = match.group(2)
        sep = match.group(3).strip() or "/"
        year = match.group(4)
        candidate = f"{case_type} {number}{sep}{year}".strip()
        if candidate not in candidates:
            candidates.append(candidate)
    
    # PATTERN 2: Flexible forms with letters/dots/spaces
    # TYPE + NUMBER + SEPARATOR + YEAR (flexible spacing)
    pattern2 = r'(?<![a-zA-Z])([A-Z][A-Z\.\(\)\s-]*?)\s*[-/]?\s*(\d+)\s*([-/]|OF)\s*(\d{4})(?![\w/])'
    
    matches2 = re.finditer(pattern2, normalized, re.IGNORECASE)
    for match in matches2:
        case_type = match.group(1).strip()
        number = match.group(2)
        sep = match.group(3).strip() or "/"
        year = match.group(4)
        candidate = f"{case_type} {number}{sep}{year}".strip()
        if candidate not in candidates:
            candidates.append(candidate)
    
    valid_cases = []
    NOISE_WORDS = {"CASE", "FILED", "AGAINST", "SAME", "FIR", "NO", "DATED", "ORDER", "ITEM", "ADD", "TRACK"}
    
    for candidate in candidates:
        norm = normalize_case_id(candidate)
        if norm:
            type_part = norm.split('-')[0]
            if type_part not in NOISE_WORDS and len(type_part) >= 2:
                logger.debug("EXTRACT_CASE: %s -> %s", candidate, norm)
                valid_cases.append(candidate.strip())
    
    if "11440" in text:
        logger.debug("TARGET_11440: candidates=%d valid=%d text_sample=%s", len(candidates), len(valid_cases), text[:100])
    
    return valid_cases

def normalize_for_comparison(case_number: str) -> str:
    """Deprecated. Use normalize_case_id."""
    return normalize_case_id(case_number) or ""
