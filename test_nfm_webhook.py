import asyncio
import json
import os
import sys

from kisna_chatbot.main import process_message

async def run_test():
    payload = {
      "object": "whatsapp_business_account",
      "entry": [{
        "id": "123",
        "changes": [{
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "123", "phone_number_id": "123"},
            "contacts": [{"profile": {"name": "Test User"}, "wa_id": "919116914178"}],
            "messages": [{
              "from": "919116914178",
              "id": "wamid.HBgMOTE5MTE2OTE0MTc4FQIAEhgWM0VCMDhC...",
              "timestamp": "1690000000",
              "type": "interactive",
              "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {
                  "response_json": "{\"flow_token\":\"1527624128967855\",\"screen_0_Order_ID_0\":\"12345\",\"screen_0_Issue_Description_1\":\"Damaged item\",\"screen_0_complaint_type_2\":\"damage\"}",
                  "body": "Sent",
                  "name": "flow"
                }
              }
            }]
          },
          "field": "messages"
        }]
      }]
    }
    
    # We are simulating what happens when main.py receives the webhook
    class MockApp:
        state = None
        
    app_state = MockApp().state
    
    # Run the message processor
    await process_message(payload, app_state, request_id="req_test_123")
    print("Test completed successfully!")

if __name__ == "__main__":
    asyncio.run(run_test())
