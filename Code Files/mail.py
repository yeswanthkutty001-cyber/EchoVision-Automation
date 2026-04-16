import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import os

# -------------------------------------------------------------
# ⚠️ SECURITY NOTE:
#   Use a Gmail App Password instead of your real password:
#   https://myaccount.google.com/apppasswords
# -------------------------------------------------------------
EMAIL_ID = "bess@festgroup.in"
EMAIL_PASSWORD = "fchddsxyrofmuxjl"   # Replace with Gmail App Password
LOGO_FILENAME = "logo.jpeg"                  # or logo.png
EXCEL_FILE = "processed_output.xlsx"                   # Excel containing Sheet2 "DAY_2"
CC_EMAIL = "rgr@fesren.com"

# -------------------------------------------------------------
# Function to send a single general email
# -------------------------------------------------------------
def send_general_email(bcc_list):
    sender_email = EMAIL_ID
    subject = "Appreciation for Visiting Fesren Energy at Wind Energy Expo 2025"

    body = """
    <html>
    <body style="font-family: Arial, sans-serif; color: #333;">
        <p>Dear Partner,</p>

        <p>We sincerely thank you for visiting our stall at the <b>Wind Energy Expo 2025 in Chennai</b>.
        It was a pleasure connecting and exchanging insights on renewable energy solutions.</p>

        <p>We would appreciate it if you could share your company <b>profile, products, or services</b>,
        to help us explore potential areas of collaboration.</p>

        <p>We look forward to staying in touch and working together toward our shared clean energy goals.</p>

        <p style="margin-top:20px;">
            Warm regards,<br>
            <b>Fesren Energy Pvt. Ltd.</b><br>
            Email: <a href="mailto:rgr@fesren.com">rgr@fesren.com</a><br>
            Address: 1st Floor, Room No. 1-97/80, Vanagaram Main Road, Athipet, Ambattur, Chennai-600058
        </p>

        <p><img src="cid:logo" alt="Fesren Energy Logo" style="width:200px; margin-top:10px;"></p>
    </body>
    </html>
    """

    # Create MIME message
    msg = MIMEMultipart("related")
    msg["From"] = sender_email
    msg["To"] = ""              # To left empty (BCC used)
    msg["Cc"] = CC_EMAIL
    msg["Subject"] = subject

    # HTML body
    msg_alternative = MIMEMultipart("alternative")
    msg.attach(msg_alternative)
    msg_alternative.attach(MIMEText(body, "html"))

    # Inline logo
    if os.path.exists(LOGO_FILENAME):
        with open(LOGO_FILENAME, "rb") as f:
            image = MIMEImage(f.read())
            image.add_header("Content-ID", "<logo>")
            image.add_header("Content-Disposition", "inline", filename=LOGO_FILENAME)
            msg.attach(image)
    else:
        print(f"⚠️ Logo file '{LOGO_FILENAME}' not found, skipping image attachment.")

    # Send via Gmail
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ID, EMAIL_PASSWORD)
            server.send_message(msg, from_addr=sender_email, to_addrs=[CC_EMAIL] + bcc_list)
            print(f"✅ General email sent successfully to {len(bcc_list)} recipients.")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

# -------------------------------------------------------------
# Main
# -------------------------------------------------------------
def main():
    # Read only sheet 'DAY_3'
    df = pd.read_excel(EXCEL_FILE, sheet_name="DAY_3")
    df.columns = [c.strip().lower() for c in df.columns]

    # Extract valid emails
    emails = []
    for email in df.get("e-mail", []):
        if isinstance(email, str) and "@" in email:
            emails.append(email.strip())

    if not emails:
        print("⚠️ No valid emails found in DAY_2 sheet.")
        return

    print(f"📧 Preparing to send to {len(emails)} recipients...")
    send_general_email(emails)

if __name__ == "__main__":
    main()