import os, json, asyncio
import numpy as np
from pathlib import Path
from datetime import datetime
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY)

DEFAULT_CRITERIA = """
1. Greeting: Did the agent greet properly and introduce themselves?
2. Empathy: Did the agent show understanding toward customer's issue?
3. Resolution: Was the customer's issue resolved?
4. Communication: Was the agent clear, polite, and professional?
5. Compliance: Did agent avoid making unauthorized promises or commitments?
6. Closing: Did agent confirm resolution and close the call properly?
"""

BURGER_SINGH_CRITERIA = [
    # Group 1 — Greeting & Introduction (15 pts)
    {"key": "greeting", "label": "Greeting done properly?", "points": 7.5, "group": "Greeting & Introduction", "negative": False},
    {"key": "agent_intro", "label": "Agent introduced themselves by name?", "points": 2.5, "group": "Greeting & Introduction", "negative": False},
    {"key": "company_info", "label": "Agent introduced the company (Burger Singh)?", "points": 5, "group": "Greeting & Introduction", "negative": False},

    # Group 2 — Ask Right Questions (20 pts)
    {"key": "location_pincode", "label": "Location & Pincode collected?", "points": 2, "group": "Ask Right Questions", "negative": False},
    {"key": "prospect_name", "label": "Prospect name collected?", "hint": "check if prospect name was mentioned/used anywhere in call — agent may already have it in CRM so check if agent used the name while speaking, or prospect mentioned it, or agent confirmed it. Mark true if name appears anywhere in conversation", "points": 0.5, "group": "Ask Right Questions", "negative": False},
    {"key": "prospect_phone", "label": "Prospect phone number collected?", "hint": "check if phone number was mentioned/used anywhere in call — agent may already have it in CRM so check if agent referenced it, prospect confirmed it, or it was mentioned anywhere. Mark true if phone number appears anywhere in conversation", "points": 0.5, "group": "Ask Right Questions", "negative": False},
    {"key": "prospect_age", "label": "Prospect age collected?", "hint": "check if prospect age was mentioned/used anywhere in call — agent may already have it in CRM so check if agent referenced it, prospect mentioned it, or it came up anywhere. Mark true if age appears anywhere in conversation", "points": 0.5, "group": "Ask Right Questions", "negative": False},
    {"key": "prospect_email", "label": "Prospect email collected?", "hint": "check if email was mentioned/used anywhere in call — agent may already have it in CRM so check if agent referenced it, prospect mentioned it, or it came up anywhere. Mark true if email appears anywhere in conversation", "points": 0.5, "group": "Ask Right Questions", "negative": False},
    {"key": "reference", "label": "Reference — how did they hear about Burger Singh?", "points": 2, "group": "Ask Right Questions", "negative": False},
    {"key": "profession", "label": "Prospect profession asked?", "points": 2, "group": "Ask Right Questions", "negative": False},
    {"key": "shop_own_rent", "label": "Shop Own or Rent discussed?", "points": 2, "group": "Ask Right Questions", "negative": False},
    {"key": "partnership_solo", "label": "Partnership or Solo discussed?", "points": 2, "group": "Ask Right Questions", "negative": False},
    {"key": "timeline", "label": "Timeline to open outlet asked?", "points": 2, "group": "Ask Right Questions", "negative": False},
    {"key": "oversee_store", "label": "Who will oversee the franchise store asked?", "points": 2, "group": "Ask Right Questions", "negative": False},
    {"key": "agreed_25_lakhs", "label": "Prospect agreed/acknowledged 25 lakhs investment?", "points": 2, "group": "Ask Right Questions", "negative": False},
    {"key": "time_dedication", "label": "Time dedication discussed?", "points": 2, "group": "Ask Right Questions", "negative": False},

    # Group 3 — Explains Co-investment Model Correctly (25 pts)
    {"key": "royalty_marketing", "label": "Royalty & Marketing explained?", "points": 5, "group": "Co-investment Model", "negative": False},
    {"key": "ground_floor_sqft", "label": "250-400 sqft ground floor requirement explained?", "points": 5, "group": "Co-investment Model", "negative": False},
    {"key": "biofrication_cost", "label": "25-20 Lakh Biofrication cost explained correctly?", "points": 15, "group": "Co-investment Model", "negative": False},

    # Group 4 — Wrong Information / False Commitment (25 pts) — NEGATIVE
    {"key": "no_guaranteed_roi", "label": "Did NOT promise guaranteed ROI/profit/fixed returns?", "points": 5, "group": "False Commitment", "negative": True},
    {"key": "no_wrong_investment", "label": "Did NOT understate investment (₹25L / ignored taxes)?", "points": 5, "group": "False Commitment", "negative": True},
    {"key": "no_reducing_involvement", "label": "Did NOT reduce involvement requirement (auto-pilot mode)?", "points": 5, "group": "False Commitment", "negative": True},
    {"key": "no_guaranteed_sales", "label": "Did NOT promise guaranteed sales/revenue?", "points": 5, "group": "False Commitment", "negative": True},
    {"key": "no_guaranteed_launch", "label": "Did NOT promise guaranteed launch timeline/approvals?", "points": 5, "group": "False Commitment", "negative": True},
]


# ─────────────────────────────────────────────
# VOICE ANALYSIS (default auditor only)
# ─────────────────────────────────────────────

def analyze_voice_acoustics(file_path, agent_segments=None):
    """Extract voice modulation and energy metrics from audio. Default auditor only."""
    try:
        import librosa
        print("[voice] Loading audio for acoustic analysis...")
        # Use soundfile directly for reliable WAV/MP3 loading
        import soundfile as _sf
        import subprocess, tempfile, os as _os
        # Convert to wav using ffmpeg first for reliability
        tmp_wav = file_path + "_tmp_analysis.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", file_path, "-ar", "16000", "-ac", "1", tmp_wav],
            capture_output=True
        )
        if _os.path.exists(tmp_wav):
            y, sr = librosa.load(tmp_wav, sr=16000, mono=True)
            _os.remove(tmp_wav)
        else:
            y, sr = librosa.load(file_path, sr=16000, mono=True)

        # If agent segments provided, extract only agent audio
        if agent_segments:
            agent_chunks = []
            for (start, end) in agent_segments:
                s = int(start * sr)
                e = int(min(end * sr, len(y)))
                if e > s:
                    agent_chunks.append(y[s:e])
            if agent_chunks:
                y = np.concatenate(agent_chunks)

        if len(y) < sr:  # less than 1 second
            return _empty_acoustics()

        # --- PITCH (Voice Modulation) ---
        pitches, magnitudes = librosa.piptrack(y=y, sr=sr, fmin=80, fmax=400)
        pitch_values = []
        for t in range(pitches.shape[1]):
            idx = magnitudes[:, t].argmax()
            p = pitches[idx, t]
            if 80 < p < 400:
                pitch_values.append(p)

        pitch_std = float(np.std(pitch_values)) if len(pitch_values) > 10 else 0.0
        pitch_mean = float(np.mean(pitch_values)) if len(pitch_values) > 10 else 0.0

        # Modulation score 0-10
        modulation_score = round(min(10.0, pitch_std / 8.0), 1)

        if pitch_std > 45:
            modulation_label = "Excellent"
        elif pitch_std > 28:
            modulation_label = "Good"
        elif pitch_std > 15:
            modulation_label = "Moderate"
        else:
            modulation_label = "Monotone"

        # --- ENERGY / ENTHUSIASM ---
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
        energy_mean = float(np.mean(rms))
        energy_max  = float(np.max(rms))

        # Energy score 0-10
        energy_score = round(min(10.0, energy_mean * 180.0), 1)

        if energy_mean > 0.07:
            energy_label = "High Energy"
        elif energy_mean > 0.045:
            energy_label = "Good Energy"
        elif energy_mean > 0.02:
            energy_label = "Low Energy"
        else:
            energy_label = "Very Low / Tired"

        # --- SILENCE RATIO ---
        silence_threshold = 0.015
        silent_frames = int(np.sum(rms < silence_threshold))
        silence_ratio = round(silent_frames / max(len(rms), 1) * 100, 1)

        # --- SPEAKING RATE (words per min estimate) ---
        # Using zero crossing rate as proxy for speech activity
        zcr = librosa.feature.zero_crossing_rate(y)[0]
        speech_frames = int(np.sum(zcr > 0.05))
        speech_seconds = speech_frames * 512 / sr
        speaking_rate_label = "Normal"
        if speech_seconds > 0:
            # rough estimate
            if silence_ratio > 40:
                speaking_rate_label = "Slow / Many Pauses"
            elif silence_ratio < 10:
                speaking_rate_label = "Fast / Few Pauses"
            else:
                speaking_rate_label = "Normal"

        print(f"[voice] Modulation: {modulation_label} ({pitch_std:.1f} Hz std) | Energy: {energy_label} ({energy_mean:.4f})")

        return {
            "voice_modulation_score": modulation_score,
            "energy_score": energy_score,
            "pitch_mean_hz": round(pitch_mean, 1),
            "pitch_variation_hz": round(pitch_std, 1),
            "energy_mean": round(energy_mean, 4),
            "silence_ratio_pct": silence_ratio,
            "modulation_label": modulation_label,
            "energy_label": energy_label,
            "speaking_rate": speaking_rate_label,
            "analysis_status": "ok",
        }

    except Exception as e:
        print(f"[voice] Analysis failed: {e}")
        return _empty_acoustics(error=str(e))


def _empty_acoustics(error=None):
    return {
        "voice_modulation_score": None,
        "energy_score": None,
        "pitch_mean_hz": None,
        "pitch_variation_hz": None,
        "energy_mean": None,
        "silence_ratio_pct": None,
        "modulation_label": "N/A",
        "energy_label": "N/A",
        "speaking_rate": "N/A",
        "analysis_status": error or "skipped",
    }


def extract_agent_segments(td, agent_speaker):
    """Get list of (start, end) tuples for agent utterances from transcript."""
    import re
    segments = []
    lines = td.get("transcript", "").split("\n")
    for i, line in enumerate(lines):
        if agent_speaker not in line:
            continue
        match = re.match(r'\[(\d+\.?\d*)s\]', line)
        if not match:
            continue
        start = float(match.group(1))
        # Try to get end from next line's timestamp
        end = start + 8.0  # default 8s window
        if i + 1 < len(lines):
            next_match = re.match(r'\[(\d+\.?\d*)s\]', lines[i + 1])
            if next_match:
                end = float(next_match.group(1))
        segments.append((start, end))
    return segments


# ─────────────────────────────────────────────
# TRANSCRIPTION (Sarvam)
# ─────────────────────────────────────────────

# Users that stay on Sarvam (empty = everyone uses AssemblyAI)
SARVAM_USERS = set()

async def transcribe_audio(file_path, user_email=None):
    if user_email and user_email.lower() in SARVAM_USERS:
        print(f"[1/3] Using Sarvam for {user_email}")
        return await _transcribe_sarvam(file_path)
    else:
        print(f"[1/3] Using AssemblyAI for {user_email or 'unknown'}")
        return await _transcribe_assemblyai(file_path)


async def _transcribe_assemblyai(file_path):
    import asyncio
    import assemblyai as aai
    aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")

    def run():
        print(f"[assemblyai] Transcribing: {file_path}")
        config = aai.TranscriptionConfig(
            speaker_labels=True,
            language_detection=True,
            speech_models=["universal-2"],
        )
        transcriber = aai.Transcriber(config=config)
        transcript = transcriber.transcribe(file_path)
        if transcript.status == aai.TranscriptStatus.error:
            raise Exception(f"AssemblyAI error: {transcript.error}")
        print(f"[assemblyai] Done. Language: {transcript.json_response.get('language_code')}. Utterances: {len(transcript.utterances)}")

        # Convert Devanagari to Hinglish Roman via LLaMA
        import re
        def needs_conversion(text):
            return bool(re.search(r"[ऀ-ॿ]", text))

        def convert_to_hinglish(utterances_text):
            if not any(needs_conversion(t) for t in utterances_text):
                return utterances_text
            from groq import Groq as GroqClient
            groq_client = GroqClient(api_key=os.getenv("GROQ_API_KEY"))
            all_text = "\n".join(utterances_text)
            response = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{
                    "role": "user",
                    "content": "Convert this Hindi/Devanagari text to natural Hinglish Roman script.\nRules:\n- Write Hindi words exactly as spoken in Roman letters\n- Keep English words as-is\n- Natural conversational style like WhatsApp Hinglish\n- Example: मेरा नाम गौरव है → Mera naam Gaurav hai\n- One line in = one line out, same order\n- Return ONLY converted lines, nothing else\n\nText:\n" + all_text
                }],
                temperature=0.1,
                max_tokens=3000,
            )
            converted = response.choices[0].message.content.strip().split("\n")
            converted = [l.strip() for l in converted if l.strip()]
            # Pad if LLaMA returned fewer lines
            while len(converted) < len(utterances_text):
                converted.append(utterances_text[len(converted)])
            return converted

        raw_texts = [u.text for u in transcript.utterances]
        hinglish_texts = convert_to_hinglish(raw_texts)
        print(f"[assemblyai] Hinglish conversion done")

        utterances = []
        for i, u in enumerate(transcript.utterances):
            utterances.append({
                "speaker_id": "0" if u.speaker == "A" else "1",
                "transcript": hinglish_texts[i] if i < len(hinglish_texts) else u.text,
                "start_time_seconds": round(u.start / 1000, 1),
                "end_time_seconds": round(u.end / 1000, 1),
            })
        return {"diarized_transcript": {"entries": utterances}}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run)


async def _transcribe_sarvam(file_path):
    print(f"[1/3] Transcribing: {file_path}")
    import asyncio
    from sarvamai import SarvamAI

    sarvam_key = os.getenv("SARVAM_API_KEY")
    client = SarvamAI(api_subscription_key=sarvam_key)

    def run_transcription():
        import time
        import requests
        job = client.speech_to_text_job.create_job(
            model="saaras:v3",
            mode="transcribe",
            language_code="unknown",
            with_diarization=True,
            num_speakers=2,
        )
        job_id = job.job_id
        print(f"Sarvam job created: {job_id}")

        upload_links = client.speech_to_text_job.get_upload_links(
            job_id=job_id, files=[os.path.basename(file_path)]
        )
        filename = os.path.basename(file_path)
        print(f"Upload URLs keys: {list(upload_links.upload_urls.keys())}")
        key = filename if filename in upload_links.upload_urls else list(upload_links.upload_urls.keys())[0]
        upload_url = upload_links.upload_urls[key].file_url
        print(f"Uploading to: {upload_url[:80]}...")
        with open(file_path, "rb") as audio_f:
            resp = requests.put(upload_url, data=audio_f, headers={"x-ms-blob-type": "BlockBlob", "Content-Type": "audio/mpeg"})
            print(f"Upload response: {resp.status_code}")
            resp.raise_for_status()
        print(f"File uploaded successfully")

        client.speech_to_text_job.start(job_id=job_id)
        print(f"Job started, polling...")

        for attempt in range(60):
            time.sleep(5)
            status = client.speech_to_text_job.get_status(job_id=job_id)
            s = str(status.job_state).lower()
            print(f"Status: {s} (attempt {attempt+1})")
            if "complete" in s or "success" in s or "done" in s:
                output_files = []
                if status.job_details:
                    for task in status.job_details:
                        for out in task.outputs:
                            output_files.append(out.file_name)
                print(f"Output files: {output_files}")
                links = client.speech_to_text_job.get_download_links(job_id=job_id, files=output_files)
                import requests as req
                dl_urls = links.download_urls if hasattr(links, "download_urls") else links.download_links
                first_key = list(dl_urls.keys())[0] if isinstance(dl_urls, dict) else 0
                result_url = dl_urls[first_key].file_url if isinstance(dl_urls, dict) else dl_urls[0].file_url
                res = req.get(result_url)
                print(f"Result fetched, status: {res.status_code}")
                return res.json()
            elif "fail" in s or "error" in s:
                raise Exception(f"Sarvam job failed: {status}")

        raise Exception("Sarvam transcription timed out")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_transcription)
    return result


def parse_transcript(dg):
    diarized = dg.get("diarized_transcript") or dg.get("transcript", {})

    utterances = []
    if isinstance(diarized, dict):
        utterances = (diarized.get("entries") or
                     diarized.get("utterances") or
                     diarized.get("segments") or [])
    elif isinstance(diarized, list):
        utterances = diarized

    if not utterances:
        plain = dg.get("transcript") or dg.get("text", "")
        if plain and isinstance(plain, str):
            return {
                "transcript": plain,
                "agent_text": plain,
                "customer_text": "",
                "agent_talk_ratio": 50.0,
                "customer_talk_ratio": 50.0,
                "total_duration": 0,
                "utterance_count": 1,
            }
        return {"error": "No transcript found in Sarvam response"}

    lines, agent_text, customer_text = [], [], []
    speakers = {}
    last_end = 0
    for utt in utterances:
        sid = (utt.get("speaker_id") or utt.get("speaker") or
               utt.get("spk_id") or "0")
        if sid not in speakers:
            label = f"SPEAKER_{chr(65 + len(speakers))}"
            speakers[sid] = label
        label = speakers[sid]
        text = (utt.get("transcript") or utt.get("text") or "").strip()
        start = round(float(utt.get("start_time_seconds") or utt.get("start", 0)), 1)
        last_end = float(utt.get("end_time_seconds") or utt.get("end", start))
        if text:
            lines.append(f"[{start}s] {label}: {text}")
            agent_text.append(text) if label == "SPEAKER_A" else customer_text.append(text)

    aw = sum(len(t.split()) for t in agent_text)
    cw = sum(len(t.split()) for t in customer_text)
    total = aw + cw or 1
    return {
        "transcript": "\n".join(lines),
        "agent_text": " ".join(agent_text),
        "customer_text": " ".join(customer_text),
        "agent_talk_ratio": round(aw / total * 100, 1),
        "customer_talk_ratio": round(cw / total * 100, 1),
        "total_duration": round(last_end, 1),
        "utterance_count": len(utterances),
    }


# ─────────────────────────────────────────────
# DEFAULT SCORING (existing clients)
# ─────────────────────────────────────────────

def score_call(td, criteria=DEFAULT_CRITERIA, client_context="", acoustics=None):
    print("[2/3] Scoring call with AI...")

    acoustic_block = ""
    if acoustics and acoustics.get("analysis_status") == "ok":
        acoustic_block = f"""
VOICE & ENERGY ANALYSIS (Agent):
- Voice Modulation: {acoustics['modulation_label']} (pitch variation: {acoustics['pitch_variation_hz']} Hz)
- Energy / Enthusiasm: {acoustics['energy_label']}
- Silence / Pause Ratio: {acoustics['silence_ratio_pct']}%
- Speaking Rate: {acoustics['speaking_rate']}

Use these acoustic metrics to score two additional parameters:
- "voice_modulation": <1-10> (10=very expressive varied tone, 1=completely flat/monotone)
- "energy_enthusiasm": <1-10> (10=highly energetic & engaged, 1=lethargic/disengaged/tired)
"""

    prompt = f"""You are an expert Call Center QA Analyst. Analyze this call transcript and provide a detailed quality assessment.

NOTE: Speakers are labeled SPEAKER_A and SPEAKER_B. Determine which one is the company agent (representative/recruiter/support staff) and which one is the customer/candidate based on the context of the conversation. The agent is typically the one who initiated the call or is representing a company/service.

TRANSCRIPT:
{td.get("transcript")}

AGENT TALK RATIO (SPEAKER_A): {td.get("agent_talk_ratio")}%
CUSTOMER TALK RATIO (SPEAKER_B): {td.get("customer_talk_ratio")}%
(Ideal agent talk ratio is 40-60%)

QA CRITERIA:
{criteria}

{f"CLIENT CONTEXT: {client_context}" if client_context else ""}
{acoustic_block}

IMPORTANT: When generating flags, only flag issues with the AGENT's behaviour. Never flag customer statements as agent issues. Always check the speaker label at each timestamp before raising a flag.

Respond ONLY with valid JSON in this exact format:
{{
  "agent_speaker": "<SPEAKER_A or SPEAKER_B — whichever is the agent>",
  "overall_score": <1-10>,
  "scores": {{
    "greeting": <1-10>,
    "empathy": <1-10>,
    "resolution": <1-10>,
    "communication": <1-10>,
    "compliance": <1-10>,
    "closing": <1-10>,
    "voice_modulation": <1-10>,
    "energy_enthusiasm": <1-10>
  }},
  "customer_sentiment": {{
    "start": "<angry|frustrated|neutral|satisfied|happy>",
    "end": "<angry|frustrated|neutral|satisfied|happy>",
    "trend": "<improved|worsened|stable>"
  }},
  "flags": ["<specific issue found, with timestamp if possible>"],
  "strengths": ["<what agent did well>"],
  "improvement_areas": ["<specific coaching suggestion>"],
  "call_summary": "<2-3 sentence summary of the call. Do NOT use SPEAKER_A or SPEAKER_B — use Agent and Customer instead>",
  "resolution_status": "<resolved|unresolved|escalated|follow_up_needed>",
  "recommendation": "<excellent|good|coaching_needed|critical_review>",
  "compliance_passed": <true|false>
}}"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=1200,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def generate_report(file_path, td, scores, acoustics=None):
    print("[3/3] Generating report...")
    agent_spk = scores.get("agent_speaker", "SPEAKER_A")
    fixed_lines = []
    for line in td.get("transcript", "").split("\n"):
        for spk in ["SPEAKER_A", "SPEAKER_B"]:
            label = "Agent" if spk == agent_spk else "Customer"
            line = line.replace(spk, label)
        fixed_lines.append(line)
    td["transcript"] = "\n".join(fixed_lines)

    report = {
        "audit_id": f"AUDIT_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "file": Path(file_path).name,
        "audited_at": datetime.now().isoformat(),
        "agent_speaker": scores.get("agent_speaker", "SPEAKER_A"),
        "call_metadata": {
            "duration_seconds": td.get("total_duration"),
            "agent_talk_ratio": td.get("agent_talk_ratio"),
            "customer_talk_ratio": td.get("customer_talk_ratio"),
            "total_turns": td.get("utterance_count"),
        },
        "scores": scores.get("scores", {}),
        "overall_score": scores.get("overall_score"),
        "customer_sentiment": scores.get("customer_sentiment"),
        "resolution_status": scores.get("resolution_status"),
        "compliance_passed": scores.get("compliance_passed"),
        "recommendation": scores.get("recommendation"),
        "flags": scores.get("flags", []),
        "strengths": scores.get("strengths", []),
        "improvement_areas": scores.get("improvement_areas", []),
        "call_summary": scores.get("call_summary"),
        "full_transcript": td.get("transcript"),
    }

    if acoustics:
        report["voice_analysis"] = acoustics

    return report


async def audit_call(file_path, criteria=DEFAULT_CRITERIA, client_context="", save_report=True, user_email=None):
    print(f"\n{'='*50}\nAuditing: {file_path}\n{'='*50}")
    dg = await transcribe_audio(file_path, user_email=user_email)
    td = parse_transcript(dg)
    if "error" in td:
        return {"error": td["error"], "file": file_path}

    # Voice analysis — default auditor only, never franchise
    agent_spk_guess = "SPEAKER_A"  # will be corrected after scoring
    agent_segments = extract_agent_segments(td, agent_spk_guess)
    acoustics = analyze_voice_acoustics(file_path, agent_segments)

    scores = score_call(td, criteria, client_context, acoustics=acoustics)
    report = generate_report(file_path, td, scores, acoustics=acoustics)

    if save_report:
        rp = Path(file_path).with_suffix(".audit.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"✅ Report saved: {rp}")
    return report


async def audit_batch(folder_path, criteria=DEFAULT_CRITERIA):
    folder = Path(folder_path)
    audio_files = list(folder.glob("*.mp3")) + list(folder.glob("*.wav"))
    if not audio_files:
        print("No audio files found")
        return []
    results = []
    for i, file in enumerate(audio_files, 1):
        print(f"\nProcessing {i}/{len(audio_files)}: {file.name}")
        try:
            report = await audit_call(str(file), criteria)
            results.append(report)
        except Exception as e:
            results.append({"error": str(e), "file": file.name})
    with open(folder / "batch_summary.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n✅ {len(results)} calls audited.")
    return results


# ─────────────────────────────────────────────
# CHECKLIST SCORING (Franchise — UNTOUCHED)
# ─────────────────────────────────────────────

def score_call_checklist(td, criteria_list):
    print("[2/3] Scoring call with checklist mode...")
    keys_and_labels = "\n".join(
        [f'{i+1}. [{c["group"]}] "{c["key"]}": {c.get("hint", c["label"])} ({c["points"]} pts){"  [NEGATIVE — return true if agent did NOT say this]" if c["negative"] else ""}' for i, c in enumerate(criteria_list)]
    )
    checks_json = ",\n    ".join([f'"{c["key"]}": {{"passed": <true|false>, "timestamp": "<start_time>s - <end_time>s or null if not found>"}}' for c in criteria_list])
    prompt = f"""You are an expert Call QA Analyst for a franchise sales team (Burger Singh).

Analyze this call transcript and evaluate each parameter below.

TRANSCRIPT:
{td.get("transcript")}

IMPORTANT RULES:
- Only evaluate AGENT behaviour, never customer statements.
- For NEGATIVE parameters: return true if agent did NOT say the wrong thing, false if agent DID make that false commitment.
- For POSITIVE parameters: return true if agent covered it, false if missed.
- Always check speaker labels before making a judgement.
- For timestamp: find where in the transcript the agent covered that parameter. Give a tight 10-second range like "45.0s - 55.0s". If not found, use null.
- Timestamps must come directly from the transcript timestamps shown as [Xs] at the start of each line.

PARAMETERS TO EVALUATE:
{keys_and_labels}

Respond ONLY with valid JSON in this exact format:
{{
  "agent_speaker": "<SPEAKER_A or SPEAKER_B — whichever is the agent>",
  "checks": {{
    {checks_json}
  }},
  "call_summary": "<2-3 sentence summary of the call. Do NOT use SPEAKER_A or SPEAKER_B — use Agent and Prospect instead>",
  "flags": ["<flag only if agent did any of these — with timestamp: (1) Made false commitment like guaranteed ROI/profit/launch/sales, (2) Understated investment amount or ignored taxes, (3) Said business runs on auto-pilot or no time needed, (4) Could not answer prospect question, (5) Interrupted or was rude to prospect, (6) Gave wrong royalty/marketing percentage, (7) Ended call without scheduling follow-up, (8) Long silence over 10 seconds>"],
  "strengths": ["<mention only if agent did any of these: (1) Built good rapport naturally, (2) Handled objections confidently, (3) Explained co-investment model clearly, (4) Collected all required prospect information, (5) Scheduled follow-up call, (6) Stayed calm under pressure, (7) Gave accurate investment and royalty information>"],
  "improvement_areas": ["<specific coaching suggestion based on what was missed or done incorrectly in this call>"]
}}"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=800,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def generate_report_checklist(file_path, td, scores, criteria_list):
    print("[3/3] Generating checklist report...")
    agent_spk = scores.get("agent_speaker", "SPEAKER_A")
    fixed_lines = []
    for line in td.get("transcript", "").split("\n"):
        for spk in ["SPEAKER_A", "SPEAKER_B"]:
            label = "Agent" if spk == agent_spk else "Customer"
            line = line.replace(spk, label)
        fixed_lines.append(line)
    td["transcript"] = "\n".join(fixed_lines)

    checks = scores.get("checks", {})
    checklist_result = []
    total_score = 0
    max_score = 0
    for c in criteria_list:
        check_data = checks.get(c["key"], {})
        if isinstance(check_data, dict):
            passed = check_data.get("passed", False)
            timestamp = check_data.get("timestamp", None)
        else:
            passed = bool(check_data)
            timestamp = None
        pts = c["points"]
        max_score += pts
        earned = pts if passed else 0
        total_score += earned
        checklist_result.append({
            "label": c["label"],
            "key": c["key"],
            "passed": passed,
            "timestamp": timestamp,
            "points_earned": earned,
            "points_max": pts,
            "group": c["group"],
            "negative": c["negative"]
        })

    return {
        "audit_id": f"AUDIT_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "file": Path(file_path).name,
        "audited_at": datetime.now().isoformat(),
        "mode": "checklist",
        "client": "burger_singh_demo",
        "agent_speaker": agent_spk,
        "call_metadata": {
            "duration_seconds": td.get("total_duration"),
            "agent_talk_ratio": td.get("agent_talk_ratio"),
            "customer_talk_ratio": td.get("customer_talk_ratio"),
            "total_turns": td.get("utterance_count"),
        },
        "checklist": checklist_result,
        "total_score": round(total_score, 1),
        "max_score": max_score,
        "score_display": f"{round(total_score, 1)}/{max_score}",
        "call_summary": scores.get("call_summary"),
        "flags": scores.get("flags", []),
        "strengths": scores.get("strengths", []),
        "improvement_areas": scores.get("improvement_areas", []),
        "full_transcript": td.get("transcript"),
    }


async def audit_call_checklist(file_path, criteria_list=BURGER_SINGH_CRITERIA):
    print(f"\n{'='*50}\nChecklist Audit: {file_path}\n{'='*50}")
    dg = await transcribe_audio(file_path)
    td = parse_transcript(dg)
    if "error" in td:
        return {"error": td["error"], "file": file_path}
    scores = score_call_checklist(td, criteria_list)
    report = generate_report_checklist(file_path, td, scores, criteria_list)
    rp = Path(file_path).with_suffix(".checklist.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Checklist report saved: {rp}")
    print(f"\n📊 Score: {report['score_display']} checks covered")
    print("─" * 40)
    for item in report["checklist"]:
        icon = "✅" if item["passed"] else "❌"
        print(f"   {icon}  {item['label']}")
    print("─" * 40)
    print(f"Summary: {report['call_summary']}")
    return report


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python auditor.py call.mp3              # standard audit")
        print("  python auditor.py call.mp3 --checklist  # Burger Singh checklist audit")
        sys.exit(1)

    path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else ""

    if mode == "--checklist":
        report = asyncio.run(audit_call_checklist(path))
    elif Path(path).is_dir():
        asyncio.run(audit_batch(path))
    else:
        report = asyncio.run(audit_call(path))
        print(f"\nAgent Speaker:  {report.get('agent_speaker')}")
        print(f"Score:          {report.get('overall_score')}/10")
        print(f"Recommendation: {report.get('recommendation')}")
        print(f"Resolution:     {report.get('resolution_status')}")
        print(f"Compliance:     {'✅ Passed' if report.get('compliance_passed') else '❌ Failed'}")
        print(f"Summary:        {report.get('call_summary')}")
        va = report.get("voice_analysis", {})
        if va.get("analysis_status") == "ok":
            print(f"Voice Modulation: {va.get('modulation_label')} ({va.get('voice_modulation_score')}/10)")
            print(f"Energy:           {va.get('energy_label')} ({va.get('energy_score')}/10)")
        if report.get("flags"):
            print(f"\n⚠️  Flags:")
            for flag in report["flags"]:
                print(f"   - {flag}")
