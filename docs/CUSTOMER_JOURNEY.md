# Kisna Chatbot — Customer Journey

This flowchart maps the end-to-end customer journey for the Kisna jewellery brand chatbot on WhatsApp. It covers greeting, the main menu, and all six customer intents using plain business language suitable for stakeholder and client reviews.

## Legend

| Color | Node type | Meaning |
|-------|-----------|---------|
| Green | Trigger | How the conversation starts |
| Yellow | Logic | Decision points where the bot chooses what to do next |
| Blue | Action | Steps the bot takes to help the customer |
| Grey | Menu | Menu screens shown to the customer |

## Customer Journey Flowchart

```mermaid
graph TD
    %% Clean, minimal styling for client presentation
    classDef trigger fill:#d1e7dd,stroke:#0f5132,stroke-width:2px,rx:8px,ry:8px
    classDef logic fill:#fff3cd,stroke:#856404,stroke-width:1px,rx:8px,ry:8px
    classDef action fill:#cff4fc,stroke:#055160,stroke-width:1px,rx:8px,ry:8px
    classDef menu fill:#e2e3e5,stroke:#383d41,stroke-width:2px,rx:10px,ry:10px

    %% MAIN ENTRY
    Start((Customer says Hi)):::trigger --> CheckUser{Is this a<br/>New Customer?}:::logic

    %% GREETING & MENU
    CheckUser -- Yes --> ShowMenu[Show Main Menu]:::menu
    CheckUser -- No --> WelcomeBack[Say Welcome Back and Show Menu]:::menu

    %% MENU OPTIONS BRANCHING
    ShowMenu --> MenuChoices{Customer Selects<br/>an Option}:::logic
    WelcomeBack --> MenuChoices

    %% 1. PRODUCT FLOW
    MenuChoices -- "Shop Products" --> ContextCheck{Did they already<br/>mention preferences?}:::logic
    ContextCheck -- No --> AskDetails[Ask for: Material, Type, & Budget via flow]:::action
    ContextCheck -- Yes --> SkipQuestions[Understand request automatically]:::action
    AskDetails --> FindProducts[Find matching items in store]:::action
    SkipQuestions --> FindProducts
    FindProducts --> ShowProducts[Show 3 Products with Buy Links and images<br/>+ Link to full catalog]:::action
    ShowProducts -- Customer says Show more --> FetchMore[Find the next 3 matching items]:::action
    FetchMore --> ShowProducts

    %% 2. OFFERS FLOW
    MenuChoices -- "View Offers" --> GetOffers[Gather all active deals]:::action
    GetOffers --> ShowOffers[Send current offers to customer]:::action

    %% 3. FIND STORE FLOW
    MenuChoices -- "Find Store Near Me" --> AskLocation[Ask for Pincode or City]:::action
    AskLocation --> ShowStores[Show closest store addresses & maps]:::action

    %% 4. TRACK ORDER FLOW
    MenuChoices -- "Track My Order" --> AskOrderDetails[sends tracking url]:::action

    %% 5. COMPLAINT / HELP FLOW
    MenuChoices -- "Help / Complaint" --> AskIssue[Sends the Complaint form and Ask customer to describe the issue]:::action
    AskIssue --> CreateTicket[Register complaint & give Ticket ID]:::action
    CreateTicket --> TransferAgent[Transfer chat to a human agent]:::action

    %% 6. FAQs / ABOUT FLOW
    MenuChoices -- "FAQs / About Kisna" --> ShowInfo[Share brand story & common questions]:::action
    ShowInfo --> AskFurther[Ask if they need anything else]:::action
```
