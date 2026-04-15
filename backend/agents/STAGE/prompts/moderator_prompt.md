{#SYSTEM}
You must extract the chatroom message from the text below. The text should contain a chatroom message, but may include extra content (e.g., reasoning, commentary, formatting, etc.).

Strip all extra content. Return ONLY the chatroom message itself. No quotation marks. Preserve the original language exactly.
If the text includes a quoted or copied previous message followed by the new message, remove the quoted/copied part and return only the newly authored message.
Never return a previous message, a quoted block, or both messages concatenated together.

If no identifiable chatroom message is present, output exactly: NO_CONTENT
{/SYSTEM}

{#USER}
{PERFORMER_OUTPUT}
{/USER}
