import { execSync } from 'node:child_process';

export default () => ({
  'tool.execute.after': async (event) => {
    try {
      const result = execSync('agent-memory hook check-error', {
        input: JSON.stringify(event),
        encoding: 'utf-8',
        timeout: 5000,
      });
      if (result.trim()) {
        return { message: result.trim() };
      }
    } catch {
      // Silently ignore errors — never block tool execution
    }
    return {};
  },
});
