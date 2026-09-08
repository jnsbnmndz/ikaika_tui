# What PSScriptAnalyzer checks here, and the two rules that are wrong for this code.
#
# An exclusion is a claim that the rule does not apply, and each one below says why. A
# rule excluded because it was noisy is a rule that will hide a real finding later, so
# nothing is excluded for volume alone - PSAvoidUsingWriteHost accounted for 240 of the
# 240 findings on this repository and is still excluded on its merits, not its count.

@{
    Severity = @('Error', 'Warning')

    ExcludeRules = @(
        # These files ARE the terminal output. Every command here is something a person
        # runs to read the result, in colour, with alignment - and Write-Output is the
        # wrong tool for that: it writes to the success stream, so it becomes the command's
        # RETURN VALUE. A step line printed with Write-Output ends up captured by any
        # caller that assigns the result, which in the sibling project is exactly how an
        # entire interface got drawn into a discarded variable.
        #
        # Write-Information is not a substitute either: it is off by default, so the
        # progress a person is waiting on would print nothing until they knew to pass
        # -InformationAction.
        'PSAvoidUsingWriteHost',

        # -WhatIf is implemented by hand in bump-version, and deliberately: the rule wants
        # [CmdletBinding(SupportsShouldProcess)], which brings a confirmation prompt with
        # it. These commands run in CI and in git hooks, where a prompt is a hang with no
        # output. -WhatIf here means "print the plan and exit", which is what it is for.
        'PSUseShouldProcessForStateChangingFunctions'
    )
}
