with open('app.py', 'r', encoding='utf-8') as f
    content = f.read()
    if 'create_text_image' in content
        print(✓ Has PIL image generation code)
    if 'subtitles=' in content
        print(✗ Still has old subtitle code (should be removed))
    if 'eleven_multilingual_v2' in content
        print(✓ Has updated ElevenLabs model)
    else
        print(✗ Has old ElevenLabs model)