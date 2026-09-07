import os
from google import genai

# Read the API key from Replit Secrets (never hardcode it directly)
api_key = os.environ["GEMINI_API_KEY"]

# Create a client - this is your connection to Google's Gemini service
client = genai.Client(api_key=api_key)

# Send a simple prompt and get a response back
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Say hello and confirm you're working, in one short sentence."
)

print(response.text)