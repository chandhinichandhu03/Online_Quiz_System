import g4f

def test():
    try:
        from g4f.Provider import DDGS
        client = g4f.client.Client(provider=DDGS)
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "Write a 5 word sentence about testing."}],
        )
        print("Success DDGS:", response.choices[0].message.content)
    except Exception as e:
        print("Error DDGS:", str(e))

if __name__ == "__main__":
    test()
