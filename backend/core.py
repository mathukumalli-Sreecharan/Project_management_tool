import os
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

# Central model initialization
_model = None

def get_model(provider="openai"):
    """
    Returns a unified GPT-4o model instance. 
    """
    global _model
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found for OpenAI.")
    return ChatOpenAI(model="gpt-4o", temperature=0, api_key=api_key)
