import re


DISPLAY_TYPE_MAP = {
    "CRLMC": "CRL.M.C.",
    "WPC": "W.P.(C)",
    "CSCOMM": "CS(COMM)",
    "FAOOS": "FAO(OS)",
    "CRLA": "CRL.A.",
    "CMM": "CM(M)",
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
    Returns a list of original case strings found.
    """
    if not text:
        return []
        
    # Regex to find potential case patterns
    # Type (letters/dots/parens) + Number + / + Year
    # We use a broad pattern to capture candidates, then validate/normalize them
    # Updated to support "OF" as separator
    pattern = r'(?<![a-zA-Z])([A-Z][A-Z\.\(\)\s-]*?\s*[-/]?\s*\d+\s*(?:[-/]|OF)\s*\d{4})'
    
    candidates = re.findall(pattern, text, re.IGNORECASE)
    valid_cases = []
    
    # Filter out noise words that might look like types
    NOISE_WORDS = {"CASE", "FILED", "AGAINST", "SAME", "FIR", "NO", "DATED", "ORDER", "ITEM", "ADD", "TRACK"}
    
    for candidate in candidates:
        # Check if it normalizes correctly
        norm = normalize_case_id(candidate)
        if norm:
            # Check if the type is just a noise word
            type_part = norm.split('-')[0]
            if type_part in NOISE_WORDS:
                continue
            valid_cases.append(candidate.strip())
            
    return valid_cases

def normalize_for_comparison(case_number: str) -> str:
    """Deprecated. Use normalize_case_id."""
    return normalize_case_id(case_number) or ""
