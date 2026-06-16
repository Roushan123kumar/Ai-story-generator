import streamlit as st
import requests
import json
import re
import os
from PIL import Image
from io import BytesIO
from fpdf import FPDF

# ========== SETUP ==========
os.makedirs("story_images", exist_ok=True)

API_KEY = "OpenRouter API key"       # <-- OpenRouter API key
HF_TOKEN = "Hugging Face token"      # <-- Hugging Face token (hf_xxxxxxxxxx)
MODEL = "anthropic/claude-3-haiku"

# ========== HELPER FUNCTIONS ==========

@st.cache_data
def generate_story(user_prompt):
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8501",
        },
        data=json.dumps({
            "model": MODEL,
            "messages": [{
                "role": "user",
                "content": f"Write a beautiful children's story based on this prompt:\n\n'{user_prompt}'\n\nUse paragraphs."
            }],
            "max_tokens": 1000
        })
    )
    result = response.json()
    if "choices" not in result:
        st.error("API Error: Check your OpenRouter API key or credits.")
        st.stop()
    return result["choices"][0]["message"]["content"].strip()


@st.cache_data
def summarize_story(story):
    paras = [p.strip() for p in story.split("\n\n") if p.strip()]
    combined_paras = [" ".join(paras[i:i+2]) for i in range(0, len(paras), 2)]
    prompts = []
    for chunk in combined_paras:
        first_sentence = re.split(r'(?<=[.!?]) +', chunk)[0]
        prompts.append(first_sentence)
    return prompts, combined_paras


def generate_image_hf(prompt, index):
    full_prompt = f"children's storybook illustration, {prompt}, colorful, cute, watercolor art style"

    # Using black-forest-labs/FLUX.1-schnell — works on new HF router
    api_url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"inputs": full_prompt}

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            img = Image.open(BytesIO(response.content))
            return img, None
        elif response.status_code == 503:
            return None, "Model is loading, please wait 30 seconds and try again"
        else:
            return None, f"Status {response.status_code}: {response.text[:150]}"
    except requests.exceptions.Timeout:
        return None, "Request timed out"
    except Exception as e:
        return None, str(e)


def generate_images(prompts):
    colors = [(210,225,240),(225,210,240),(210,240,225),(240,225,210),(240,210,225),(225,240,210)]
    image_paths = []
    progress = st.progress(0, text="Generating illustrations...")

    for i, prompt in enumerate(prompts):
        path = f"story_images/page_{i+1}.png"
        progress.progress(i / len(prompts), text=f"Generating image {i+1} of {len(prompts)}...")

        img, error = generate_image_hf(prompt, i)

        if img:
            img = img.resize((768, 432))
            img.save(path)
            st.toast(f"Image {i+1} done!", icon="✅")
        else:
            st.warning(f"Image {i+1} failed: {error}. Using placeholder.")
            placeholder = Image.new("RGB", (768, 432), color=colors[i % len(colors)])
            placeholder.save(path)

        image_paths.append(path)

    progress.progress(1.0, text="All illustrations done!")
    return image_paths


# ========== PDF CLASS ==========

class StoryPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)
        self.set_font("Helvetica", size=12)

    def header(self):
        if self.page == 1:
            self.set_font("Helvetica", "B", 24)
            self.cell(0, 20, txt=st.session_state.title, ln=True, align="C")
            self.ln(10)

    def add_content_page(self, text, image_path):
        self.add_page()
        clean_text = text.encode("latin-1", "replace").decode("latin-1")
        self.set_font("Helvetica", size=14)
        self.multi_cell(0, 8, clean_text)
        self.ln(10)
        if image_path and os.path.exists(image_path):
            img = Image.open(image_path)
            width = self.w - 30
            aspect = img.height / img.width
            self.image(image_path, x=15, y=self.get_y(), w=width, h=width * aspect)


def create_pdf(story_chunks, image_paths):
    pdf = StoryPDF()
    pdf.set_title(st.session_state.title)
    for text, img_path in zip(story_chunks, image_paths):
        pdf.add_content_page(text, img_path)
    return pdf.output(dest="S").encode("latin-1")


# ========== STREAMLIT UI ==========

st.set_page_config(page_title="📖 AI Storybook Generator", layout="wide")
st.title("📖 AI Storybook Generator")

user_input = st.text_input("Enter your story theme or prompt:")
st.session_state.title = user_input.strip() or "AI Generated Storybook"

if st.button("Generate Storybook"):

    if not user_input.strip():
        st.warning("Please enter a story prompt.")
        st.stop()

    if not API_KEY:
        st.error("Please add your OpenRouter API key in app.py")
        st.stop()

    if not HF_TOKEN:
        st.error("Please add your Hugging Face token in app.py")
        st.stop()

    with st.spinner("📖 Writing story..."):
        story = generate_story(user_input)

    with st.spinner("🔍 Preparing pages..."):
        prompts, story_chunks = summarize_story(story)

    st.info(f"Generating {len(prompts)} illustrations... this may take 2-3 minutes.")
    image_paths = generate_images(prompts)

    st.subheader("Your Generated Storybook")

    for text, img_path in zip(story_chunks, image_paths):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(
                f"<div style='font-size:16px;text-align:justify'>{text}</div>",
                unsafe_allow_html=True
            )
        with col2:
            st.image(img_path, width=500)
        st.markdown("---")

    with st.spinner("📄 Creating PDF..."):
        pdf_bytes = create_pdf(story_chunks, image_paths)

    st.download_button(
        "⬇️ Download Storybook PDF",
        data=pdf_bytes,
        file_name=f"{st.session_state.title.replace(' ','_')}.pdf",
        mime="application/pdf"
    )