from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
from datetime import datetime
import spacy
import dateparser
import re

# Load the spaCy model
nlp = spacy.load("en_core_web_sm")

def get_db_connection():
    conn = sqlite3.connect('transactions.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_category_for_merchant(merchant):
    """
    Look up the default category for a given merchant using the default_categories table.
    This query checks if the merchant string contains the merchant_pattern.
    """
    conn = get_db_connection()
    query = """
    SELECT category FROM default_categories 
    WHERE ? LIKE '%' || merchant_pattern || '%'
    LIMIT 1
    """
    cursor = conn.execute(query, (merchant,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row['category']
    else:
        return 'uncategorized'

def parse_transaction(text):
    """
    Parse a transaction text to extract amount, merchant, date, and category.

    This function:
      - Extracts the amount using spaCy's MONEY entity and falls back to regex if needed.
      - Extracts the date by first using a regex looking for "on <Month> <day>, <year>" and falls back to spaCy's DATE entities.
      - Attempts to extract the merchant using patterns such as "transfer to <merchant> on", "with <merchant> on",
        or "at <merchant> on". If these fail, it falls back to spaCy's ORG/PRODUCT entities.
      - For simple inputs like "$123 hamza", if no merchant is detected, it takes the token immediately following the money value.
    """
    # Process text with spaCy
    doc = nlp(text)
    
    # Initialize variables
    amount = None
    parsed_date = None

    # Extract amount using spaCy's MONEY entity
    for ent in doc.ents:
        if ent.label_ == "MONEY" and amount is None:
            try:
                amount = float(ent.text.replace('$', '').replace(',', '').strip())
            except Exception:
                pass

    # Fallback: if spaCy did not extract the amount, use regex.
    if amount is None:
        amount_match = re.search(r'\$(\d+(?:\.\d+)?)', text)
        if amount_match:
            try:
                amount = float(amount_match.group(1))
            except Exception:
                pass

    if amount is None:
        raise ValueError("Could not find a valid amount.")

    # Extract date using regex first.
    date_match = re.search(r'on\s+([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})', text, re.IGNORECASE)
    if date_match:
        date_text = date_match.group(1)
        parsed_date = dateparser.parse(date_text)
    else:
        # Fallback: use spaCy's DATE entities
        for ent in doc.ents:
            if ent.label_ == "DATE":
                parsed_date = dateparser.parse(ent.text)
                if parsed_date:
                    break

    if parsed_date is None:
        parsed_date = datetime.today()

    # Extract merchant using multiple patterns:
    merchant = None
    # Pattern 1: "transfer to <merchant> on"
    merchant_match = re.search(r'transfer to\s+(.*?)\s+on', text, re.IGNORECASE)
    if merchant_match:
        merchant = merchant_match.group(1).strip()
    else:
        # Pattern 2: "with <merchant> on"
        merchant_match = re.search(r'with\s+(.*?)\s+on', text, re.IGNORECASE)
        if merchant_match:
            merchant = merchant_match.group(1).strip()
        else:
            # Pattern 3: "at <merchant> on"
            merchant_match = re.search(r'at\s+(.*?)\s+on', text, re.IGNORECASE)
            if merchant_match:
                merchant = merchant_match.group(1).strip()

    # Fallback: use spaCy's ORG or PRODUCT entities.
    if merchant is None:
        for ent in doc.ents:
            if ent.label_ in ("ORG", "PRODUCT"):
                merchant = ent.text.strip()
                break

    # Additional fallback for simple input like "$123 hamza"
    if merchant is None:
        tokens = text.split()
        for i, token in enumerate(tokens):
            if token.startswith('$'):
                if i + 1 < len(tokens):
                    merchant = tokens[i + 1]
                    break

    if merchant is None:
        merchant = "unknown"

    date_str = parsed_date.strftime("%Y-%m-%d")
    category = get_category_for_merchant(merchant)
    
    return {
        "amount": amount,
        "merchant": merchant,
        "date": date_str,
        "category": category
    }

def parse_transactions(text):
    """
    Splits the input text into multiple transaction messages using newline as the delimiter,
    and returns a list of parsed transaction dictionaries.
    """
    lines = text.splitlines()
    transactions = []
    for line in lines:
        line = line.strip()
        if line:
            try:
                parsed = parse_transaction(line)
                transactions.append(parsed)
            except Exception as e:
                print(f"Error parsing transaction: {line}\nError: {e}")
    return transactions
