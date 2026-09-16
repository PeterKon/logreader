Documentation:
Do not add feature descriptions, implementation details, or usage walkthroughs unless explicitly requested.
Do not create additional documentation files unless requested.
When documentation is requested, describe the current behavior from the user's perspective: controls, purpose, and workflows.
Attempt a concise but correct explanation of elements when additions are requested.
Update existing explanations directly rather than describing changes as a changelog.

Workflow:
Do not commit, push, pull, or stash unless explicitly requested. Read-only Git inspection is allowed.
Do not use em dashes. Use regular hyphens (-) instead.
Run tests appropriate to the changes. For UI changes, inspect rendered screenshots when appearance or spacing is affected.

UI language:
Use concise, direct wording based on terms users see in the app. Avoid internal terminology when a familiar term is sufficient.
Describe what a control does. Avoid tooltips that merely repeat an obvious label or explain a familiar navigation action.
Avoid redundant labels, repeated nouns, and unnecessary qualifiers.
Preserve important scope distinctions when simplifying wording, such as whether an action affects all patterns or only some.
When the user supplies replacement text, follow it closely. Correct only clear grammatical mistakes unless asked to rewrite.

Testing:
Add or update tests where they protect meaningful behavior or prevent regressions. Assess existing coverage first and keep each test focused on what matters.