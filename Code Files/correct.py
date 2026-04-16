import pandas as pd
import re
import phonenumbers
import dns.resolver

# ---------- Utility Functions ----------

def capitalize_company(name):
    return str(name).upper().strip() if pd.notna(name) else name

def capitalize_name(name):
    if pd.isna(name):
        return name
    return ' '.join([part.capitalize() for part in str(name).split()])

def is_valid_email_format(email):
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return bool(re.match(pattern, str(email).strip()))

def check_email_exists(email):
    try:
        domain = email.split('@')[1]
        records = dns.resolver.resolve(domain, 'MX')
        return len(records) > 0
    except Exception:
        return False

def validate_phone(phone):
    try:
        parsed = phonenumbers.parse(str(phone), "IN")  # assuming India
        return phonenumbers.is_valid_number(parsed)
    except Exception:
        return False


# ---------- Core Processing for One Sheet ----------

def process_dataframe(df):
    # Clean column names
    df.columns = [str(col).strip().lower() for col in df.columns]

    def get_col(possible_names):
        for name in df.columns:
            if any(name == cand.lower() for cand in possible_names):
                return name
        return None

    col_company = get_col(["Company"])
    col_name = get_col(["Name"])
    col_email = get_col(["e-Mail", "Email"])
    col_contact = get_col(["Contact", "Phone", "Mobile"])

    # 1️⃣ Capitalize company names
    if col_company:
        df[col_company] = df[col_company].apply(capitalize_company)

    # 2️⃣ Capitalize each word in Name
    if col_name:
        df[col_name] = df[col_name].apply(capitalize_name)

    # 3️⃣ Validate e-Mails
    if col_email:
        df['Email_Format_Valid'] = df[col_email].apply(is_valid_email_format)
        df['Email_Domain_Exists'] = df[col_email].apply(
            lambda x: check_email_exists(x) if is_valid_email_format(x) else False
        )

    # 4️⃣ Validate phone numbers
    if col_contact:
        df['Phone_Valid'] = df[col_contact].apply(validate_phone)

    return df


# ---------- Main Script for Multiple Sheets ----------

def process_excel(input_path, output_path="Companies_List_processed_output.xlsx"):
    # Read all sheets
    all_sheets = pd.read_excel(input_path, sheet_name=None)
    print(f"Detected sheets: {list(all_sheets.keys())}")

    processed_sheets = {}

    for sheet_name, df in all_sheets.items():
        print(f"\n🔹 Processing sheet: {sheet_name}")
        processed_sheets[sheet_name] = process_dataframe(df)
        print(f"✅ Done: {sheet_name}")

    # Write all processed sheets back to one Excel file
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in processed_sheets.items():
            df.to_excel(writer, index=False, sheet_name=sheet_name)

    print(f"\n✅ All sheets processed. File saved as: {output_path}")


# ---------- Run ----------
if __name__ == "__main__":
    process_excel("Companies List.xlsx")