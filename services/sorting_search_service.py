import re
from typing import List, Dict, Any, Optional

ROMAN_TO_NUM = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "1ST": 1,
    "2ND": 2,
    "3RD": 3,
    "4TH": 4
}

NUM_TO_ROMAN = {
    1: "I",
    2: "II",
    3: "III",
    4: "IV"
}

STATUS_PRIORITY = {
    "Rejected": 1,
    "Not Generated": 2,
    "Generated": 3,
    "Submitted to HOD": 4,
    "Pending HOD": 4,
    "Pending Dean": 4,
    "Pending Principal": 4,
    "Submitted to Principal": 4,
    "HOD Approved": 5,
    "Dean Approved": 5,
    "Partially Approved": 5,
    "Approved": 6
}

def parse_class_info(class_name: str, department: str = None) -> Dict[str, Any]:
    """
    Parses class name string into structured metadata:
    - original_name: str
    - formatted_class: str
    - department: str
    - section: str
    - year_num: int (1, 2, 3, 4)
    - year_roman: str ('I', 'II', 'III', 'IV')
    - batch: str (e.g. '2024-2028')
    - is_odd_year: bool (True for 1st & 3rd year / Sem 1, 3, 5, 7)
    - is_even_year: bool (True for 2nd & 4th year / Sem 2, 4, 6, 8)
    """
    name = (class_name or "").strip()
    dept = (department or "").strip().upper()
    sec = ""
    year_num = 4  # Default to 4th year if unspecified
    batch = "2024-2028"

    # Pattern 1: "IV BE CSE A" or "III BE IT B"
    match_roman_be = re.search(r"^(IV|III|II|I)\s+BE\s+(\w+)(?:\s+(\w+))?$", name, re.IGNORECASE)
    if match_roman_be:
        r_str = match_roman_be.group(1).upper()
        year_num = ROMAN_TO_NUM.get(r_str, 4)
        if not dept:
            dept = match_roman_be.group(2).upper()
        sec = match_roman_be.group(3).upper() if match_roman_be.group(3) else "A"

    # Pattern 2: "2024-2028-CSE-A" or "2024-2028_CSE_A"
    match_batch = re.search(r"^(\d{4}[-_]\d{4})[-_](\w+)(?:[-_](\w+))?$", name, re.IGNORECASE)
    if not match_roman_be and match_batch:
        batch = match_batch.group(1).replace("_", "-")
        if not dept:
            dept = match_batch.group(2).upper()
        sec = match_batch.group(3).upper() if match_batch.group(3) else "A"
        try:
            start_year = int(batch.split("-")[0])
            diff = 2024 - start_year
            year_num = max(1, min(4, 4 - diff))
        except Exception:
            year_num = 4

    # Pattern 3: "IV-CSE-A" or "IV_BE_CSE_A"
    match_hyphen_roman = re.search(r"^(IV|III|II|I)[-_](?:BE[-_])?(\w+)(?:[-_](\w+))?$", name, re.IGNORECASE)
    if not match_roman_be and not match_batch and match_hyphen_roman:
        r_str = match_hyphen_roman.group(1).upper()
        year_num = ROMAN_TO_NUM.get(r_str, 4)
        if not dept:
            dept = match_hyphen_roman.group(2).upper()
        sec = match_hyphen_roman.group(3).upper() if match_hyphen_roman.group(3) else "A"

    year_roman = NUM_TO_ROMAN.get(year_num, "IV")
    
    year_batch_map = {
        4: "2024-2028 (IV Year)",
        3: "2023-2027 (III Year)",
        2: "2022-2026 (II Year)",
        1: "2021-2025 (I Year)"
    }
    batch_display = year_batch_map.get(year_num, f"{batch} ({year_roman} Year)")

    is_odd_year = (year_num in [1, 3])
    is_even_year = (year_num in [2, 4])

    formatted_class = f"{year_roman} BE {dept} {sec}".strip() if (dept and sec) else name

    return {
        "original_name": name,
        "formatted_class": formatted_class,
        "department": dept,
        "section": sec,
        "year_num": year_num,
        "year_roman": year_roman,
        "batch": batch,
        "batch_display": batch_display,
        "is_odd_year": is_odd_year,
        "is_even_year": is_even_year
    }

def filter_by_odd_even_year(items: List[Dict[str, Any]], year_branch: str = "all") -> List[Dict[str, Any]]:
    """
    Filters a list of items (each having 'class' or 'class_name' or 'department') by year branch:
    - 'all': Returns all items
    - 'odd': Returns items matching 1st & 3rd academic year (Sem 1, 3, 5, 7)
    - 'even': Returns items matching 2nd & 4th academic year (Sem 2, 4, 6, 8)
    """
    if not year_branch or year_branch.lower() == "all":
        return items

    branch = year_branch.lower().strip()
    filtered = []

    for item in items:
        c_name = item.get("class") or item.get("class_name") or ""
        dept = item.get("department") or ""
        info = parse_class_info(c_name, dept)

        if branch == "odd" and info["is_odd_year"]:
            filtered.append(item)
        elif branch == "even" and info["is_even_year"]:
            filtered.append(item)

    return filtered

def group_by_batch_and_class(classes_list: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Groups a list of class metadata dictionaries by Batch (Batch-wise -> Class-wise)
    for HOD dashboard.
    Returns dict keyed by batch_display with lists of classes sorted by class name.
    """
    grouped = {}
    for c in classes_list:
        c_name = c.get("class") or c.get("class_name") or ""
        dept = c.get("department") or ""
        info = parse_class_info(c_name, dept)

        c["parsed_info"] = info
        batch_key = info["batch_display"]

        if batch_key not in grouped:
            grouped[batch_key] = []
        grouped[batch_key].append(c)

    sorted_grouped = {}
    batch_keys_sorted = sorted(
        grouped.keys(),
        key=lambda b: parse_class_info(grouped[b][0].get("class", ""))["year_num"],
        reverse=True
    )

    for b in batch_keys_sorted:
        grouped[b].sort(key=lambda item: item.get("class", ""))
        sorted_grouped[b] = grouped[b]

    return sorted_grouped

def group_by_dept_batch_class(classes_list: List[Dict[str, Any]], cluster_depts: Optional[List[str]] = None) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """
    Groups a list of classes by Department -> Batch -> Class for Dean dashboard.
    If cluster_depts is provided, filters strictly to those departments.
    """
    result = {}
    for c in classes_list:
        dept = (c.get("department") or "").upper()
        if cluster_depts and dept not in [d.upper() for d in cluster_depts]:
            continue

        c_name = c.get("class") or c.get("class_name") or ""
        info = parse_class_info(c_name, dept)
        c["parsed_info"] = info
        batch_key = info["batch_display"]

        if dept not in result:
            result[dept] = {}
        if batch_key not in result[dept]:
            result[dept][batch_key] = []

        result[dept][batch_key].append(c)

    sorted_result = {}
    for dept in sorted(result.keys()):
        sorted_result[dept] = {}
        batch_keys = sorted(
            result[dept].keys(),
            key=lambda b: parse_class_info(result[dept][b][0].get("class", ""))["year_num"],
            reverse=True
        )
        for b in batch_keys:
            result[dept][b].sort(key=lambda item: item.get("class", ""))
            sorted_result[dept][b] = result[dept][b]

    return sorted_result

def group_college_academic_year(batches_list: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """
    Groups all college batches into Academic Year order:
    Department -> Batch (Academic-Year sorted) -> Classes
    for Principal and Office dashboards.
    """
    result = {}
    for b in batches_list:
        dept = (b.get("department") or "").upper()
        c_name = b.get("class") or b.get("class_name") or ""
        info = parse_class_info(c_name, dept)
        b["parsed_info"] = info
        batch_key = info["batch_display"]

        if dept not in result:
            result[dept] = {}
        if batch_key not in result[dept]:
            result[dept][batch_key] = []

        result[dept][batch_key].append(b)

    sorted_college = {}
    for dept in sorted(result.keys()):
        sorted_college[dept] = {}
        b_sorted_keys = sorted(
            result[dept].keys(),
            key=lambda k: parse_class_info(result[dept][k][0].get("class") or result[dept][k][0].get("class_name", ""))["year_num"],
            reverse=True
        )
        for b_key in b_sorted_keys:
            result[dept][b_key].sort(key=lambda item: item.get("class") or item.get("class_name", ""))
            sorted_college[dept][b_key] = result[dept][b_key]

    return sorted_college

def sort_students(students: List[Dict[str, Any]], sort_by: str = "priority") -> List[Dict[str, Any]]:
    """
    Sorts a list of student dictionary records based on requested criteria:
    - 'priority': Status Priority (Rejected first, Approved last) + Register Number
    - 'reg_asc': Register Number Ascending
    - 'reg_desc': Register Number Descending
    - 'name_asc': Student Name A-Z
    - 'name_desc': Student Name Z-A
    """
    if not students:
        return []

    if sort_by == "reg_asc":
        return sorted(students, key=lambda s: str(s.get("register_number", "")).strip())
    elif sort_by == "reg_desc":
        return sorted(students, key=lambda s: str(s.get("register_number", "")).strip(), reverse=True)
    elif sort_by == "name_asc":
        return sorted(students, key=lambda s: str(s.get("student_name", "")).strip().lower())
    elif sort_by == "name_desc":
        return sorted(students, key=lambda s: str(s.get("student_name", "")).strip().lower(), reverse=True)
    else:
        return sorted(students, key=lambda s: (STATUS_PRIORITY.get(s.get("status", ""), 99), str(s.get("register_number", "")).strip()))
