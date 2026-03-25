import asyncio
import os
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from agents.mutation_agent import MutationAgent

# Set mock ENV logic to bypass crash if unset, or use the real keys if the user actually set them locally
os.environ["AZURE_OPENAI_DEPLOYMENT"] = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
os.environ["AZURE_OPENAI_ENDPOINT"] = os.environ.get("AZURE_OPENAI_ENDPOINT", "https://mock-endpoint.com/")
os.environ["AZURE_OPENAI_API_KEY"] = os.environ.get("AZURE_OPENAI_API_KEY", "mock-key")

async def test_mutation():
    try:
        kernel = Kernel()
        kernel.add_service(
            AzureChatCompletion(
                service_id="gpt4o",
                deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT"],
                endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                api_version="2024-02-01",
            )
        )
        agent = MutationAgent(kernel)
        
        print("--- TESTING MUTATION AGENT ---")
        para = "The convolution integral is given by y(t) = ∫ x(τ)h(t-τ)dτ."
        doubt = "I don't get the h(t-tau) part, why is it flipped and shifted?"
        
        print(f"Original: {para}")
        print(f"Doubt: {doubt}")
        
        mutated, gap = await agent.mutate(para, doubt)
        print(f"\n[Mutated Note]:\n{mutated}")
        print(f"\n[Diagnosed Gap]:\n{gap}")
        
    except Exception as e:
        print(f"Mutation test failed (Expected if Azure OpenAI keys are 'mock-key'): {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_mutation())
