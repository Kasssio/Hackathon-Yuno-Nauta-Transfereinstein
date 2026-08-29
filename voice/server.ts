import "dotenv/config";
import express from "express";
import path from "node:path";
import { sessionConfig } from "./session-config.js";

const app = express();
app.use(express.static(path.join(process.cwd(), "public")));

app.post("/session", async (_req, res) => {
  try {
    const r = await fetch("https://api.openai.com/v1/realtime/client_secrets", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.OPENAI_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        session: {
          type: "realtime",
          model: "gpt-realtime-2.1",
          output_modalities: ["audio"],
          instructions: sessionConfig.instructions,
          audio: {
            input: {
              transcription: { model: "gpt-live-transcribe" },
              turn_detection: {
                type: "semantic_vad",
                create_response: true,
                interrupt_response: true,
              },
            },
            output: { voice: sessionConfig.voice },
          },
          tools: sessionConfig.tools,
          tool_choice: "auto",
        },
      }),
    });
    res.status(r.status).json(await r.json());
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: "mint failed" });
  }
});

app.listen(3000, () => console.log("http://localhost:3000"));
