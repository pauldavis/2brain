This project is about storing, indexing, and viewing documents in a variety of formats for personal use.

The documents I want to store have relatively rich and complex formatting and structure. The first two types of documents are chat records from the AI assistants ChatGPT and Claude. These include rich markdown-formatted text and sections of specialized content like source code for programs.

I want to be able to parse these documents (starting with the AI chat records, but eventually others), see summaries of the documents overall and of their various components. 

I want to be able to copy or export each documenet component/segment individually. 

I want to be able to view each document in a faithful presentation of its original content.

I want these documents and segments be indexed and searchable by metadata like date or size or title, keywords from a controlled vocabulary maintained by the tool, free text, or semantic indexing.

It will be a web app.

The backing storage will be a PostgreSQL database.

Let's start by analyzing the structure of ChatGPT export files and Claude export file and designing a common data structure to parse store the components of these types of file.

Please search the web to find these file specifications, capture them into reference files in this project, and propose a core data structure that can represent them well and can meet my requirements.





