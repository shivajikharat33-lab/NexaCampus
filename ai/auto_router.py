"""
Auto-assign complaints to departments based on category.
Update CATEGORY_TO_DEPARTMENT to match your college's department names.
"""

CATEGORY_TO_DEPARTMENT = {
    "Infrastructure":  "Civil & Maintenance Department",
    "Electrical":      "Electrical Department",
    "Plumbing":        "Plumbing & Sanitation Department",
    "Cleanliness":     "Housekeeping Department",
    "Security":        "Security Department",
    "IT":              "IT Department",
    "Canteen":         "Canteen Management",
    "Garden":          "Horticulture Department",
    "Parking":         "Administration Department",
    "Library":         "Library Department",
    "Sports":          "Sports Department",
    "Transport":       "Transport Department",
    "Medical":         "Medical Centre",
    "Hostel":          "Hostel Administration",
    "General":         "Administration Department",
}


def auto_assign_department(category: str) -> str:
    """
    Returns the department name for a given category.
    Falls back to Administration Department if category not mapped.
    """
    return CATEGORY_TO_DEPARTMENT.get(category, "Administration Department")