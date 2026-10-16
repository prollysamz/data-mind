from openai import OpenAI
local = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
r = local.chat.completions.create(
    model="gemma4:e2b",
    messages=[{"role": "user", "content": "Reply with the word OK"}],
)
print(r.choices[0].message.content)