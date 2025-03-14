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
      - Extracts the amount using spaCy's MONEY entity.
      - Extracts the date by first looking for a pattern like "on <Month> <day>, <year>".
      - Falls back to spaCy's DATE entity if the regex doesn't match.
      - Extracts the merchant using patterns such as "transfer to <merchant> on" or "with <merchant> on".
    
    Example input:
      "Chase acct 3050: Your $3,690.35 external transfer to MIDWEST LOAN on Mar 3, 2025 at 4:43 PM ET was more than the $0.00 in your Alerts settings."
      
    Expected output:
      {
         "amount": 3690.35,
         "merchant": "MIDWEST LOAN",
         "date": "2025-03-03",
         "category": <determined from DB>
      }
    """
    # Process text with spaCy
    doc = nlp(text)
    
    # Initialize variables
    amount = None
    parsed_date = None

    # Extract amount using spaCy entities
    for ent in doc.ents:
        if ent.label_ == "MONEY" and amount is None:
            try:
                amount = float(ent.text.replace('$', '').replace(',', '').strip())
            except Exception:
                pass

    # First, try to extract the date using a regex for the "on <Month> <day>, <year>" pattern.
    date_match = re.search(r'on\s+([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})', text, re.IGNORECASE)
    if date_match:
        date_text = date_match.group(1)
        parsed_date = dateparser.parse(date_text)
    else:
        # Fallback: use spaCy's DATE entity if regex didn't match.
        for ent in doc.ents:
            if ent.label_ == "DATE":
                parsed_date = dateparser.parse(ent.text)
                if parsed_date:
                    break

    # Default to today's date if no date found
    if parsed_date is None:
        parsed_date = datetime.today()

    # Extract merchant using multiple patterns:
    merchant = None
    # Try first: "transfer to <merchant> on"
    merchant_match = re.search(r'transfer to\s+(.*?)\s+on', text, re.IGNORECASE)
    if merchant_match:
        merchant = merchant_match.group(1).strip()
    else:
        # Fallback: "with <merchant> on"
        merchant_match = re.search(r'with\s+(.*?)\s+on', text, re.IGNORECASE)
        if merchant_match:
            merchant = merchant_match.group(1).strip()
    if merchant is None:
        # Final fallback: use spaCy's ORG or PRODUCT entities
        for ent in doc.ents:
            if ent.label_ in ("ORG", "PRODUCT"):
                merchant = ent.text.strip()
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
