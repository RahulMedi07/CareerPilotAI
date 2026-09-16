import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next regenerates AGENTS.md and CLAUDE.md on every dev start. The project
  // keeps its documentation in three files at the repository root, and two
  // auto-generated copies that nobody maintains would contradict them.
  agentRules: false,
};

export default nextConfig;
