"""Regression tests for the matchers that have broken before.

Every case here comes from a real bug: `apac` matching `capacity`,
`hr ` killing `$90/hr`, `.net` never matching `ASP.NET`, university dates
counted as work experience.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..',
                                'skills', 'linkedin-jobhunt', 'scripts'))
import lib, score, export


def check(label, got, want):
    status = 'PASS' if got == want else 'FAIL'
    print(f'{status}  {label}: got={got!r} want={want!r}')
    return got == want


def main():
    ok = []

    # word-boundary matching must not fire on substrings
    ok.append(check('gc not in gcp', lib.any_kw('gcp azure', ['gc']), []))
    ok.append(check('opt not in option', lib.any_kw('optimize', ['opt']), []))
    ok.append(check('.net inside ASP.NET', lib.any_kw('asp.net mvc', ['.net']), ['.net']))
    ok.append(check('node family collapses',
                    lib.any_kw_family('node.js nodejs', ['node', 'node.js', 'nodejs']),
                    ['node.js']))

    # role gate
    ok.append(check('hr in $90/hr survives',
                    score.role_group_of('Data Engineer | $90/hr Remote'), 'Data Engineer'))
    ok.append(check('typo Enginer caught',
                    score.role_group_of('Data Enginer'), 'Data Engineer'))
    ok.append(check('AI engineer rejected',
                    score.role_group_of('AI Engineer - Generative AI'), None))
    ok.append(check('frontend rejected',
                    score.role_group_of('FrontEnd Web Developer'), None))

    # years required: must take the real bar, not the easiest number
    ok.append(check('picks 7 not 3',
                    score.required_years('7+ years of professional experience. '
                                         '3+ years hands-on.'), 7))

    # US work-authorization detection
    for txt in ['applicants must be currently authorized to work in the united states',
                'we will not sponsor applicants for work visas',
                'us citizenship is a contractual requirement']:
        ok.append(check('us lock: ' + txt[:34],
                        bool(score.US_LOCK_RE.search(txt)), True))

    # region mapping must not dump everything into one bucket
    ok.append(check('US state maps', export.region_of('Bismarck, ND', ''), 'Mỹ'))
    ok.append(check('India maps', export.region_of('Bengaluru, Karnataka, India', ''), 'Ấn Độ'))
    ok.append(check('Hanoi maps', export.region_of('Hanoi, Vietnam', ''), 'Hà Nội'))

    # hard gate drops what the candidate cannot take
    ok.append(check('US-locked dropped',
                    export.can_apply({'reach': 'khoá trong Mỹ', 'seniority': ''}), False))
    ok.append(check('over-level dropped',
                    export.can_apply({'reach': 'remote toàn cầu', 'seniority': 'quá tầm'}), False))
    ok.append(check('good one kept',
                    export.can_apply({'reach': 'Việt Nam', 'seniority': '3+ năm'}), True))

    print(f'\n{sum(ok)}/{len(ok)} passed')
    return 0 if all(ok) else 1


if __name__ == '__main__':
    sys.exit(main())
