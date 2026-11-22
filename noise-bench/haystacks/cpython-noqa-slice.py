    LESSEQUAL  '<='          (1, 5) (1, 7)
    NUMBER     '255'         (1, 8) (1, 11)
    """)

        self.check_tokenize('0o123 <= 0O123', """\
    NUMBER     '0o123'       (1, 0) (1, 5)
    LESSEQUAL  '<='          (1, 6) (1, 8)
    NUMBER     '0O123'       (1, 9) (1, 14)
    """)

        self.check_tokenize('1234567 > ~0x15', """\
    NUMBER     '1234567'     (1, 0) (1, 7)
    GREATER    '>'           (1, 8) (1, 9)
    TILDE      '~'           (1, 10) (1, 11)
    NUMBER     '0x15'        (1, 11) (1, 15)
    """)

        self.check_tokenize('2134568 != 1231515', """\
    NUMBER     '2134568'     (1, 0) (1, 7)
    NOTEQUAL   '!='          (1, 8) (1, 10)
    NUMBER     '1231515'     (1, 11) (1, 18)
    """)

        self.check_tokenize('(-124561-1) & 200000000', """\
    LPAR       '('           (1, 0) (1, 1)
    MINUS      '-'           (1, 1) (1, 2)
    NUMBER     '124561'      (1, 2) (1, 8)
    MINUS      '-'           (1, 8) (1, 9)
    NUMBER     '1'           (1, 9) (1, 10)
    RPAR       ')'           (1, 10) (1, 11)
    AMPER      '&'           (1, 12) (1, 13)
    NUMBER     '200000000'   (1, 14) (1, 23)
    """)

        self.check_tokenize('0xdeadbeef != -1', """\
    NUMBER     '0xdeadbeef'  (1, 0) (1, 10)
    NOTEQUAL   '!='          (1, 11) (1, 13)
    MINUS      '-'           (1, 14) (1, 15)
    NUMBER     '1'           (1, 15) (1, 16)
    """)

        self.check_tokenize('0xdeadc0de & 12345', """\
    NUMBER     '0xdeadc0de'  (1, 0) (1, 10)
    AMPER      '&'           (1, 11) (1, 12)
    NUMBER     '12345'       (1, 13) (1, 18)
    """)

        self.check_tokenize('0xFF & 0x15 | 1234', """\
    NUMBER     '0xFF'        (1, 0) (1, 4)
    AMPER      '&'           (1, 5) (1, 6)
    NUMBER     '0x15'        (1, 7) (1, 11)
    VBAR       '|'           (1, 12) (1, 13)
    NUMBER     '1234'        (1, 14) (1, 18)
    """)

    def test_float(self):

        self.check_tokenize('x = 3.14159', """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    NUMBER     '3.14159'     (1, 4) (1, 11)
    """)

        self.check_tokenize('x = 314159.', """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    NUMBER     '314159.'     (1, 4) (1, 11)
    """)

        self.check_tokenize('x = .314159', """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    NUMBER     '.314159'     (1, 4) (1, 11)
    """)

        self.check_tokenize('x = 3e14159', """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    NUMBER     '3e14159'     (1, 4) (1, 11)
    """)

        self.check_tokenize('x = 3E123', """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    NUMBER     '3E123'       (1, 4) (1, 9)
    """)

        self.check_tokenize('x+y = 3e-1230', """\
    NAME       'x'           (1, 0) (1, 1)
    PLUS       '+'           (1, 1) (1, 2)
    NAME       'y'           (1, 2) (1, 3)
    EQUAL      '='           (1, 4) (1, 5)
    NUMBER     '3e-1230'     (1, 6) (1, 13)
    """)

        self.check_tokenize('x = 3.14e159', """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    NUMBER     '3.14e159'    (1, 4) (1, 12)
    """)

    def test_string(self):

        self.check_tokenize('x = \'\'; y = ""', """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    STRING     "''"          (1, 4) (1, 6)
    SEMI       ';'           (1, 6) (1, 7)
    NAME       'y'           (1, 8) (1, 9)
    EQUAL      '='           (1, 10) (1, 11)
    STRING     '""'          (1, 12) (1, 14)
    """)

        self.check_tokenize('x = \'"\'; y = "\'"', """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    STRING     '\\'"\\''       (1, 4) (1, 7)
    SEMI       ';'           (1, 7) (1, 8)
    NAME       'y'           (1, 9) (1, 10)
    EQUAL      '='           (1, 11) (1, 12)
    STRING     '"\\'"'        (1, 13) (1, 16)
    """)

        self.check_tokenize('x = "doesn\'t "shrink", does it"', """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    STRING     '"doesn\\'t "' (1, 4) (1, 14)
    NAME       'shrink'      (1, 14) (1, 20)
    STRING     '", does it"' (1, 20) (1, 31)
    """)

        self.check_tokenize("x = 'abc' + 'ABC'", """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    STRING     "'abc'"       (1, 4) (1, 9)
    PLUS       '+'           (1, 10) (1, 11)
    STRING     "'ABC'"       (1, 12) (1, 17)
    """)

        self.check_tokenize('y = "ABC" + "ABC"', """\
    NAME       'y'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    STRING     '"ABC"'       (1, 4) (1, 9)
    PLUS       '+'           (1, 10) (1, 11)
    STRING     '"ABC"'       (1, 12) (1, 17)
    """)

        self.check_tokenize("x = r'abc' + r'ABC' + R'ABC' + R'ABC'", """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    STRING     "r'abc'"      (1, 4) (1, 10)
    PLUS       '+'           (1, 11) (1, 12)
    STRING     "r'ABC'"      (1, 13) (1, 19)
    PLUS       '+'           (1, 20) (1, 21)
    STRING     "R'ABC'"      (1, 22) (1, 28)
    PLUS       '+'           (1, 29) (1, 30)
    STRING     "R'ABC'"      (1, 31) (1, 37)
    """)

        self.check_tokenize('y = r"abc" + r"ABC" + R"ABC" + R"ABC"', """\
    NAME       'y'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    STRING     'r"abc"'      (1, 4) (1, 10)
    PLUS       '+'           (1, 11) (1, 12)
    STRING     'r"ABC"'      (1, 13) (1, 19)
    PLUS       '+'           (1, 20) (1, 21)
    STRING     'R"ABC"'      (1, 22) (1, 28)
    PLUS       '+'           (1, 29) (1, 30)
    STRING     'R"ABC"'      (1, 31) (1, 37)
    """)

        self.check_tokenize("u'abc' + U'abc'", """\
    STRING     "u'abc'"      (1, 0) (1, 6)
    PLUS       '+'           (1, 7) (1, 8)
    STRING     "U'abc'"      (1, 9) (1, 15)
    """)

        self.check_tokenize('u"abc" + U"abc"', """\
    STRING     'u"abc"'      (1, 0) (1, 6)
    PLUS       '+'           (1, 7) (1, 8)
    STRING     'U"abc"'      (1, 9) (1, 15)
    """)

        self.check_tokenize("b'abc' + B'abc'", """\
    STRING     "b'abc'"      (1, 0) (1, 6)
    PLUS       '+'           (1, 7) (1, 8)
    STRING     "B'abc'"      (1, 9) (1, 15)
    """)

        self.check_tokenize('b"abc" + B"abc"', """\
    STRING     'b"abc"'      (1, 0) (1, 6)
    PLUS       '+'           (1, 7) (1, 8)
    STRING     'B"abc"'      (1, 9) (1, 15)
    """)

        self.check_tokenize("br'abc' + bR'abc' + Br'abc' + BR'abc'", """\
    STRING     "br'abc'"     (1, 0) (1, 7)
    PLUS       '+'           (1, 8) (1, 9)
    STRING     "bR'abc'"     (1, 10) (1, 17)
    PLUS       '+'           (1, 18) (1, 19)
    STRING     "Br'abc'"     (1, 20) (1, 27)
    PLUS       '+'           (1, 28) (1, 29)
    STRING     "BR'abc'"     (1, 30) (1, 37)
    """)

        self.check_tokenize('br"abc" + bR"abc" + Br"abc" + BR"abc"', """\
    STRING     'br"abc"'     (1, 0) (1, 7)
    PLUS       '+'           (1, 8) (1, 9)
    STRING     'bR"abc"'     (1, 10) (1, 17)
    PLUS       '+'           (1, 18) (1, 19)
    STRING     'Br"abc"'     (1, 20) (1, 27)
    PLUS       '+'           (1, 28) (1, 29)
    STRING     'BR"abc"'     (1, 30) (1, 37)
    """)

        self.check_tokenize("rb'abc' + rB'abc' + Rb'abc' + RB'abc'", """\
    STRING     "rb'abc'"     (1, 0) (1, 7)
    PLUS       '+'           (1, 8) (1, 9)
    STRING     "rB'abc'"     (1, 10) (1, 17)
    PLUS       '+'           (1, 18) (1, 19)
    STRING     "Rb'abc'"     (1, 20) (1, 27)
    PLUS       '+'           (1, 28) (1, 29)
    STRING     "RB'abc'"     (1, 30) (1, 37)
    """)

        self.check_tokenize('rb"abc" + rB"abc" + Rb"abc" + RB"abc"', """\
    STRING     'rb"abc"'     (1, 0) (1, 7)
    PLUS       '+'           (1, 8) (1, 9)
    STRING     'rB"abc"'     (1, 10) (1, 17)
    PLUS       '+'           (1, 18) (1, 19)
    STRING     'Rb"abc"'     (1, 20) (1, 27)
    PLUS       '+'           (1, 28) (1, 29)
    STRING     'RB"abc"'     (1, 30) (1, 37)
    """)

        self.check_tokenize('"a\\\nde\\\nfg"', """\
    STRING     '"a\\\\\\nde\\\\\\nfg"\' (1, 0) (3, 3)
    """)

        self.check_tokenize('u"a\\\nde"', """\
    STRING     'u"a\\\\\\nde"\'  (1, 0) (2, 3)
    """)

        self.check_tokenize('rb"a\\\nd"', """\
    STRING     'rb"a\\\\\\nd"\'  (1, 0) (2, 2)
    """)

        self.check_tokenize(r'"""a\
b"""', """\
    STRING     '\"\""a\\\\\\nb\"\""' (1, 0) (2, 4)
    """)
        self.check_tokenize(r'u"""a\
b"""', """\
    STRING     'u\"\""a\\\\\\nb\"\""' (1, 0) (2, 4)
    """)
        self.check_tokenize(r'rb"""a\
b\
c"""', """\
    STRING     'rb"\""a\\\\\\nb\\\\\\nc"\""' (1, 0) (3, 4)
    """)

        self.check_tokenize('f"abc"', """\
    STRING     'f"abc"'      (1, 0) (1, 6)
    """)

        self.check_tokenize('fR"a{b}c"', """\
    STRING     'fR"a{b}c"'   (1, 0) (1, 9)
    """)

        self.check_tokenize('f"""abc"""', """\
    STRING     'f\"\"\"abc\"\"\"'  (1, 0) (1, 10)
    """)

        self.check_tokenize(r'f"abc\
def"', """\
    STRING     'f"abc\\\\\\ndef"' (1, 0) (2, 4)
    """)

        self.check_tokenize(r'Rf"abc\
def"', """\
    STRING     'Rf"abc\\\\\\ndef"' (1, 0) (2, 4)
    """)

    def test_function(self):

        self.check_tokenize('def d22(a, b, c=2, d=2, *k): pass', """\
    NAME       'def'         (1, 0) (1, 3)
    NAME       'd22'         (1, 4) (1, 7)
    LPAR       '('           (1, 7) (1, 8)
    NAME       'a'           (1, 8) (1, 9)
    COMMA      ','           (1, 9) (1, 10)
    NAME       'b'           (1, 11) (1, 12)
    COMMA      ','           (1, 12) (1, 13)
    NAME       'c'           (1, 14) (1, 15)
    EQUAL      '='           (1, 15) (1, 16)
    NUMBER     '2'           (1, 16) (1, 17)
    COMMA      ','           (1, 17) (1, 18)
    NAME       'd'           (1, 19) (1, 20)
    EQUAL      '='           (1, 20) (1, 21)
    NUMBER     '2'           (1, 21) (1, 22)
    COMMA      ','           (1, 22) (1, 23)
    STAR       '*'           (1, 24) (1, 25)
    NAME       'k'           (1, 25) (1, 26)
    RPAR       ')'           (1, 26) (1, 27)
    COLON      ':'           (1, 27) (1, 28)
    NAME       'pass'        (1, 29) (1, 33)
    """)

        self.check_tokenize('def d01v_(a=1, *k, **w): pass', """\
    NAME       'def'         (1, 0) (1, 3)
    NAME       'd01v_'       (1, 4) (1, 9)
    LPAR       '('           (1, 9) (1, 10)
    NAME       'a'           (1, 10) (1, 11)
    EQUAL      '='           (1, 11) (1, 12)
    NUMBER     '1'           (1, 12) (1, 13)
    COMMA      ','           (1, 13) (1, 14)
    STAR       '*'           (1, 15) (1, 16)
    NAME       'k'           (1, 16) (1, 17)
    COMMA      ','           (1, 17) (1, 18)
    DOUBLESTAR '**'          (1, 19) (1, 21)
    NAME       'w'           (1, 21) (1, 22)
    RPAR       ')'           (1, 22) (1, 23)
    COLON      ':'           (1, 23) (1, 24)
    NAME       'pass'        (1, 25) (1, 29)
    """)

        self.check_tokenize('def d23(a: str, b: int=3) -> int: pass', """\
    NAME       'def'         (1, 0) (1, 3)
    NAME       'd23'         (1, 4) (1, 7)
    LPAR       '('           (1, 7) (1, 8)
    NAME       'a'           (1, 8) (1, 9)
    COLON      ':'           (1, 9) (1, 10)
    NAME       'str'         (1, 11) (1, 14)
    COMMA      ','           (1, 14) (1, 15)
    NAME       'b'           (1, 16) (1, 17)
    COLON      ':'           (1, 17) (1, 18)
    NAME       'int'         (1, 19) (1, 22)
    EQUAL      '='           (1, 22) (1, 23)
    NUMBER     '3'           (1, 23) (1, 24)
    RPAR       ')'           (1, 24) (1, 25)
    RARROW     '->'          (1, 26) (1, 28)
    NAME       'int'         (1, 29) (1, 32)
    COLON      ':'           (1, 32) (1, 33)
    NAME       'pass'        (1, 34) (1, 38)
    """)

    def test_comparison(self):

        self.check_tokenize("if 1 < 1 > 1 == 1 >= 5 <= 0x15 <= 0x12 != "
                            "1 and 5 in 1 not in 1 is 1 or 5 is not 1: pass", """\
    NAME       'if'          (1, 0) (1, 2)
    NUMBER     '1'           (1, 3) (1, 4)
    LESS       '<'           (1, 5) (1, 6)
    NUMBER     '1'           (1, 7) (1, 8)
    GREATER    '>'           (1, 9) (1, 10)
    NUMBER     '1'           (1, 11) (1, 12)
    EQEQUAL    '=='          (1, 13) (1, 15)
    NUMBER     '1'           (1, 16) (1, 17)
    GREATEREQUAL '>='          (1, 18) (1, 20)
    NUMBER     '5'           (1, 21) (1, 22)
    LESSEQUAL  '<='          (1, 23) (1, 25)
    NUMBER     '0x15'        (1, 26) (1, 30)
    LESSEQUAL  '<='          (1, 31) (1, 33)
    NUMBER     '0x12'        (1, 34) (1, 38)
    NOTEQUAL   '!='          (1, 39) (1, 41)
    NUMBER     '1'           (1, 42) (1, 43)
    NAME       'and'         (1, 44) (1, 47)
    NUMBER     '5'           (1, 48) (1, 49)
    NAME       'in'          (1, 50) (1, 52)
    NUMBER     '1'           (1, 53) (1, 54)
    NAME       'not'         (1, 55) (1, 58)
    NAME       'in'          (1, 59) (1, 61)
    NUMBER     '1'           (1, 62) (1, 63)
    NAME       'is'          (1, 64) (1, 66)
    NUMBER     '1'           (1, 67) (1, 68)
    NAME       'or'          (1, 69) (1, 71)
    NUMBER     '5'           (1, 72) (1, 73)
    NAME       'is'          (1, 74) (1, 76)
    NAME       'not'         (1, 77) (1, 80)
    NUMBER     '1'           (1, 81) (1, 82)
    COLON      ':'           (1, 82) (1, 83)
    NAME       'pass'        (1, 84) (1, 88)
    """)

    def test_additive(self):

        self.check_tokenize('x = 1 - y + 15 - 1 + 0x124 + z + a[5]', """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    NUMBER     '1'           (1, 4) (1, 5)
    MINUS      '-'           (1, 6) (1, 7)
    NAME       'y'           (1, 8) (1, 9)
    PLUS       '+'           (1, 10) (1, 11)
    NUMBER     '15'          (1, 12) (1, 14)
    MINUS      '-'           (1, 15) (1, 16)
    NUMBER     '1'           (1, 17) (1, 18)
    PLUS       '+'           (1, 19) (1, 20)
    NUMBER     '0x124'       (1, 21) (1, 26)
    PLUS       '+'           (1, 27) (1, 28)
    NAME       'z'           (1, 29) (1, 30)
    PLUS       '+'           (1, 31) (1, 32)
    NAME       'a'           (1, 33) (1, 34)
    LSQB       '['           (1, 34) (1, 35)
    NUMBER     '5'           (1, 35) (1, 36)
    RSQB       ']'           (1, 36) (1, 37)
    """)

    def test_multiplicative(self):

        self.check_tokenize('x = 1//1*1/5*12%0x12@42', """\
    NAME       'x'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    NUMBER     '1'           (1, 4) (1, 5)
    DOUBLESLASH '//'          (1, 5) (1, 7)
    NUMBER     '1'           (1, 7) (1, 8)
    STAR       '*'           (1, 8) (1, 9)
    NUMBER     '1'           (1, 9) (1, 10)
    SLASH      '/'           (1, 10) (1, 11)
    NUMBER     '5'           (1, 11) (1, 12)
    STAR       '*'           (1, 12) (1, 13)
    NUMBER     '12'          (1, 13) (1, 15)
    PERCENT    '%'           (1, 15) (1, 16)
    NUMBER     '0x12'        (1, 16) (1, 20)
    AT         '@'           (1, 20) (1, 21)
    NUMBER     '42'          (1, 21) (1, 23)
    """)

    def test_unary(self):

        self.check_tokenize('~1 ^ 1 & 1 |1 ^ -1', """\
    TILDE      '~'           (1, 0) (1, 1)
    NUMBER     '1'           (1, 1) (1, 2)
    CIRCUMFLEX '^'           (1, 3) (1, 4)
    NUMBER     '1'           (1, 5) (1, 6)
    AMPER      '&'           (1, 7) (1, 8)
    NUMBER     '1'           (1, 9) (1, 10)
    VBAR       '|'           (1, 11) (1, 12)
    NUMBER     '1'           (1, 12) (1, 13)
    CIRCUMFLEX '^'           (1, 14) (1, 15)
    MINUS      '-'           (1, 16) (1, 17)
    NUMBER     '1'           (1, 17) (1, 18)
    """)

        self.check_tokenize('-1*1/1+1*1//1 - ---1**1', """\
    MINUS      '-'           (1, 0) (1, 1)
    NUMBER     '1'           (1, 1) (1, 2)
    STAR       '*'           (1, 2) (1, 3)
    NUMBER     '1'           (1, 3) (1, 4)
    SLASH      '/'           (1, 4) (1, 5)
    NUMBER     '1'           (1, 5) (1, 6)
    PLUS       '+'           (1, 6) (1, 7)
    NUMBER     '1'           (1, 7) (1, 8)
    STAR       '*'           (1, 8) (1, 9)
    NUMBER     '1'           (1, 9) (1, 10)
    DOUBLESLASH '//'          (1, 10) (1, 12)
    NUMBER     '1'           (1, 12) (1, 13)
    MINUS      '-'           (1, 14) (1, 15)
    MINUS      '-'           (1, 16) (1, 17)
    MINUS      '-'           (1, 17) (1, 18)
    MINUS      '-'           (1, 18) (1, 19)
    NUMBER     '1'           (1, 19) (1, 20)
    DOUBLESTAR '**'          (1, 20) (1, 22)
    NUMBER     '1'           (1, 22) (1, 23)
    """)

    def test_selector(self):

        self.check_tokenize("import sys, time\nx = sys.modules['time'].time()", """\
    NAME       'import'      (1, 0) (1, 6)
    NAME       'sys'         (1, 7) (1, 10)
    COMMA      ','           (1, 10) (1, 11)
    NAME       'time'        (1, 12) (1, 16)
    NEWLINE    ''            (1, 16) (1, 16)
    NAME       'x'           (2, 0) (2, 1)
    EQUAL      '='           (2, 2) (2, 3)
    NAME       'sys'         (2, 4) (2, 7)
    DOT        '.'           (2, 7) (2, 8)
    NAME       'modules'     (2, 8) (2, 15)
    LSQB       '['           (2, 15) (2, 16)
    STRING     "'time'"      (2, 16) (2, 22)
    RSQB       ']'           (2, 22) (2, 23)
    DOT        '.'           (2, 23) (2, 24)
    NAME       'time'        (2, 24) (2, 28)
    LPAR       '('           (2, 28) (2, 29)
    RPAR       ')'           (2, 29) (2, 30)
    """)

    def test_method(self):

        self.check_tokenize('@staticmethod\ndef foo(x,y): pass', """\
    AT         '@'           (1, 0) (1, 1)
    NAME       'staticmethod' (1, 1) (1, 13)
    NEWLINE    ''            (1, 13) (1, 13)
    NAME       'def'         (2, 0) (2, 3)
    NAME       'foo'         (2, 4) (2, 7)
    LPAR       '('           (2, 7) (2, 8)
    NAME       'x'           (2, 8) (2, 9)
    COMMA      ','           (2, 9) (2, 10)
    NAME       'y'           (2, 10) (2, 11)
    RPAR       ')'           (2, 11) (2, 12)
    COLON      ':'           (2, 12) (2, 13)
    NAME       'pass'        (2, 14) (2, 18)
    """)

    def test_tabs(self):

        self.check_tokenize('@staticmethod\ndef foo(x,y): pass', """\
    AT         '@'           (1, 0) (1, 1)
    NAME       'staticmethod' (1, 1) (1, 13)
    NEWLINE    ''            (1, 13) (1, 13)
    NAME       'def'         (2, 0) (2, 3)
    NAME       'foo'         (2, 4) (2, 7)
    LPAR       '('           (2, 7) (2, 8)
    NAME       'x'           (2, 8) (2, 9)
    COMMA      ','           (2, 9) (2, 10)
    NAME       'y'           (2, 10) (2, 11)
    RPAR       ')'           (2, 11) (2, 12)
    COLON      ':'           (2, 12) (2, 13)
    NAME       'pass'        (2, 14) (2, 18)
    """)

    def test_async(self):

        self.check_tokenize('async = 1', """\
    ASYNC      'async'       (1, 0) (1, 5)
    EQUAL      '='           (1, 6) (1, 7)
    NUMBER     '1'           (1, 8) (1, 9)
    """)

        self.check_tokenize('a = (async = 1)', """\
    NAME       'a'           (1, 0) (1, 1)
    EQUAL      '='           (1, 2) (1, 3)
    LPAR       '('           (1, 4) (1, 5)
    ASYNC      'async'       (1, 5) (1, 10)
    EQUAL      '='           (1, 11) (1, 12)
    NUMBER     '1'           (1, 13) (1, 14)
    RPAR       ')'           (1, 14) (1, 15)
    """)

        self.check_tokenize('async()', """\
    ASYNC      'async'       (1, 0) (1, 5)
    LPAR       '('           (1, 5) (1, 6)
    RPAR       ')'           (1, 6) (1, 7)
    """)

        self.check_tokenize('class async(Bar):pass', """\
    NAME       'class'       (1, 0) (1, 5)
    ASYNC      'async'       (1, 6) (1, 11)
    LPAR       '('           (1, 11) (1, 12)
    NAME       'Bar'         (1, 12) (1, 15)
    RPAR       ')'           (1, 15) (1, 16)
    COLON      ':'           (1, 16) (1, 17)
    NAME       'pass'        (1, 17) (1, 21)
    """)

        self.check_tokenize('class async:pass', """\
    NAME       'class'       (1, 0) (1, 5)
    ASYNC      'async'       (1, 6) (1, 11)
    COLON      ':'           (1, 11) (1, 12)
    NAME       'pass'        (1, 12) (1, 16)
    """)

        self.check_tokenize('await = 1', """\
    AWAIT      'await'       (1, 0) (1, 5)
    EQUAL      '='           (1, 6) (1, 7)
    NUMBER     '1'           (1, 8) (1, 9)
    """)

        self.check_tokenize('foo.async', """\
    NAME       'foo'         (1, 0) (1, 3)
    DOT        '.'           (1, 3) (1, 4)
    ASYNC      'async'       (1, 4) (1, 9)
    """)

        self.check_tokenize('async for a in b: pass', """\
    ASYNC      'async'       (1, 0) (1, 5)
    NAME       'for'         (1, 6) (1, 9)
    NAME       'a'           (1, 10) (1, 11)
    NAME       'in'          (1, 12) (1, 14)
    NAME       'b'           (1, 15) (1, 16)
    COLON      ':'           (1, 16) (1, 17)
    NAME       'pass'        (1, 18) (1, 22)
    """)

        self.check_tokenize('async with a as b: pass', """\
    ASYNC      'async'       (1, 0) (1, 5)
    NAME       'with'        (1, 6) (1, 10)
    NAME       'a'           (1, 11) (1, 12)
    NAME       'as'          (1, 13) (1, 15)
    NAME       'b'           (1, 16) (1, 17)
    COLON      ':'           (1, 17) (1, 18)
    NAME       'pass'        (1, 19) (1, 23)
    """)

        self.check_tokenize('async.foo', """\
    ASYNC      'async'       (1, 0) (1, 5)
    DOT        '.'           (1, 5) (1, 6)
    NAME       'foo'         (1, 6) (1, 9)
    """)

        self.check_tokenize('async', """\
    ASYNC      'async'       (1, 0) (1, 5)
    """)

        self.check_tokenize('async\n#comment\nawait', """\
    ASYNC      'async'       (1, 0) (1, 5)
    NEWLINE    ''            (1, 5) (1, 5)
    AWAIT      'await'       (3, 0) (3, 5)
    """)

        self.check_tokenize('async\n...\nawait', """\
    ASYNC      'async'       (1, 0) (1, 5)
    NEWLINE    ''            (1, 5) (1, 5)
    ELLIPSIS   '...'         (2, 0) (2, 3)
    NEWLINE    ''            (2, 3) (2, 3)
    AWAIT      'await'       (3, 0) (3, 5)
    """)

        self.check_tokenize('async\nawait', """\
    ASYNC      'async'       (1, 0) (1, 5)
    NEWLINE    ''            (1, 5) (1, 5)
    AWAIT      'await'       (2, 0) (2, 5)
    """)

        self.check_tokenize('foo.async + 1', """\
    NAME       'foo'         (1, 0) (1, 3)
    DOT        '.'           (1, 3) (1, 4)
    ASYNC      'async'       (1, 4) (1, 9)
    PLUS       '+'           (1, 10) (1, 11)
    NUMBER     '1'           (1, 12) (1, 13)
    """)

        self.check_tokenize('async def foo(): pass', """\
    ASYNC      'async'       (1, 0) (1, 5)
    NAME       'def'         (1, 6) (1, 9)
    NAME       'foo'         (1, 10) (1, 13)
    LPAR       '('           (1, 13) (1, 14)
    RPAR       ')'           (1, 14) (1, 15)
    COLON      ':'           (1, 15) (1, 16)
    NAME       'pass'        (1, 17) (1, 21)
    """)

        self.check_tokenize('''\
async def foo():
  def foo(await):
    await = 1
  if 1:
    await
async += 1
''', """\
    ASYNC      'async'       (1, 0) (1, 5)
    NAME       'def'         (1, 6) (1, 9)
    NAME       'foo'         (1, 10) (1, 13)
    LPAR       '('           (1, 13) (1, 14)
    RPAR       ')'           (1, 14) (1, 15)
    COLON      ':'           (1, 15) (1, 16)
    NEWLINE    ''            (1, 16) (1, 16)
    INDENT     ''            (2, -1) (2, -1)
    NAME       'def'         (2, 2) (2, 5)
    NAME       'foo'         (2, 6) (2, 9)
    LPAR       '('           (2, 9) (2, 10)
    AWAIT      'await'       (2, 10) (2, 15)
    RPAR       ')'           (2, 15) (2, 16)
    COLON      ':'           (2, 16) (2, 17)
    NEWLINE    ''            (2, 17) (2, 17)
    INDENT     ''            (3, -1) (3, -1)
    AWAIT      'await'       (3, 4) (3, 9)
    EQUAL      '='           (3, 10) (3, 11)
    NUMBER     '1'           (3, 12) (3, 13)
    NEWLINE    ''            (3, 13) (3, 13)
    DEDENT     ''            (4, -1) (4, -1)
    NAME       'if'          (4, 2) (4, 4)
    NUMBER     '1'           (4, 5) (4, 6)
    COLON      ':'           (4, 6) (4, 7)
    NEWLINE    ''            (4, 7) (4, 7)
    INDENT     ''            (5, -1) (5, -1)
    AWAIT      'await'       (5, 4) (5, 9)
    NEWLINE    ''            (5, 9) (5, 9)
    DEDENT     ''            (6, -1) (6, -1)
    DEDENT     ''            (6, -1) (6, -1)
    ASYNC      'async'       (6, 0) (6, 5)
    PLUSEQUAL  '+='          (6, 6) (6, 8)
    NUMBER     '1'           (6, 9) (6, 10)
    NEWLINE    ''            (6, 10) (6, 10)
    """)

        self.check_tokenize('async def foo():\n  async for i in 1: pass', """\
    ASYNC      'async'       (1, 0) (1, 5)
    NAME       'def'         (1, 6) (1, 9)
    NAME       'foo'         (1, 10) (1, 13)
    LPAR       '('           (1, 13) (1, 14)
    RPAR       ')'           (1, 14) (1, 15)
    COLON      ':'           (1, 15) (1, 16)
    NEWLINE    ''            (1, 16) (1, 16)
    INDENT     ''            (2, -1) (2, -1)
    ASYNC      'async'       (2, 2) (2, 7)
    NAME       'for'         (2, 8) (2, 11)
    NAME       'i'           (2, 12) (2, 13)
    NAME       'in'          (2, 14) (2, 16)
    NUMBER     '1'           (2, 17) (2, 18)
    COLON      ':'           (2, 18) (2, 19)
    NAME       'pass'        (2, 20) (2, 24)
    DEDENT     ''            (2, -1) (2, -1)
    """)

        self.check_tokenize('async def foo(async): await', """\
    ASYNC      'async'       (1, 0) (1, 5)
    NAME       'def'         (1, 6) (1, 9)
    NAME       'foo'         (1, 10) (1, 13)
    LPAR       '('           (1, 13) (1, 14)
    ASYNC      'async'       (1, 14) (1, 19)
    RPAR       ')'           (1, 19) (1, 20)
    COLON      ':'           (1, 20) (1, 21)
    AWAIT      'await'       (1, 22) (1, 27)
    """)

        self.check_tokenize('''\
def f():

  def baz(): pass
  async def bar(): pass

  await = 2''', """\
    NAME       'def'         (1, 0) (1, 3)
    NAME       'f'           (1, 4) (1, 5)
    LPAR       '('           (1, 5) (1, 6)
    RPAR       ')'           (1, 6) (1, 7)
    COLON      ':'           (1, 7) (1, 8)
    NEWLINE    ''            (1, 8) (1, 8)
    INDENT     ''            (3, -1) (3, -1)
    NAME       'def'         (3, 2) (3, 5)
    NAME       'baz'         (3, 6) (3, 9)
    LPAR       '('           (3, 9) (3, 10)
    RPAR       ')'           (3, 10) (3, 11)
    COLON      ':'           (3, 11) (3, 12)
    NAME       'pass'        (3, 13) (3, 17)
    NEWLINE    ''            (3, 17) (3, 17)
    ASYNC      'async'       (4, 2) (4, 7)
    NAME       'def'         (4, 8) (4, 11)
    NAME       'bar'         (4, 12) (4, 15)
    LPAR       '('           (4, 15) (4, 16)
    RPAR       ')'           (4, 16) (4, 17)
    COLON      ':'           (4, 17) (4, 18)
    NAME       'pass'        (4, 19) (4, 23)
    NEWLINE    ''            (4, 23) (4, 23)
    AWAIT      'await'       (6, 2) (6, 7)
    EQUAL      '='           (6, 8) (6, 9)
    NUMBER     '2'           (6, 10) (6, 11)
    DEDENT     ''            (6, -1) (6, -1)
    """)

        self.check_tokenize('''\
async def f():

  def baz(): pass
  async def bar(): pass

  await = 2''', """\
    ASYNC      'async'       (1, 0) (1, 5)
    NAME       'def'         (1, 6) (1, 9)
    NAME       'f'           (1, 10) (1, 11)
    LPAR       '('           (1, 11) (1, 12)
    RPAR       ')'           (1, 12) (1, 13)
    COLON      ':'           (1, 13) (1, 14)
    NEWLINE    ''            (1, 14) (1, 14)
    INDENT     ''            (3, -1) (3, -1)
    NAME       'def'         (3, 2) (3, 5)
    NAME       'baz'         (3, 6) (3, 9)
    LPAR       '('           (3, 9) (3, 10)
    RPAR       ')'           (3, 10) (3, 11)
    COLON      ':'           (3, 11) (3, 12)
    NAME       'pass'        (3, 13) (3, 17)
    NEWLINE    ''            (3, 17) (3, 17)
    ASYNC      'async'       (4, 2) (4, 7)
    NAME       'def'         (4, 8) (4, 11)
    NAME       'bar'         (4, 12) (4, 15)
    LPAR       '('           (4, 15) (4, 16)
    RPAR       ')'           (4, 16) (4, 17)
    COLON      ':'           (4, 17) (4, 18)
    NAME       'pass'        (4, 19) (4, 23)
    NEWLINE    ''            (4, 23) (4, 23)
    AWAIT      'await'       (6, 2) (6, 7)
    EQUAL      '='           (6, 8) (6, 9)
    NUMBER     '2'           (6, 10) (6, 11)
    DEDENT     ''            (6, -1) (6, -1)
    """)

    def test_unicode(self):

        self.check_tokenize("Örter = u'places'\ngrün = U'green'", """\
    NAME       'Örter'       (1, 0) (1, 6)
    EQUAL      '='           (1, 7) (1, 8)
    STRING     "u'places'"   (1, 9) (1, 18)
    NEWLINE    ''            (1, 18) (1, 18)
    NAME       'grün'        (2, 0) (2, 5)
    EQUAL      '='           (2, 6) (2, 7)
    STRING     "U'green'"    (2, 8) (2, 16)
    """)

    def test_invalid_syntax(self):
        def get_tokens(string):
            return list(_generate_tokens_from_c_tokenizer(string))

        self.assertRaises(SyntaxError, get_tokens, "(1+2]")
        self.assertRaises(SyntaxError, get_tokens, "(1+2}")
        self.assertRaises(SyntaxError, get_tokens, "{1+2]")

        self.assertRaises(SyntaxError, get_tokens, "1_")
        self.assertRaises(SyntaxError, get_tokens, "1.2_")
        self.assertRaises(SyntaxError, get_tokens, "1e2_")
        self.assertRaises(SyntaxError, get_tokens, "1e+")

        self.assertRaises(SyntaxError, get_tokens, "\xa0")
        self.assertRaises(SyntaxError, get_tokens, "€")

        self.assertRaises(SyntaxError, get_tokens, "0b12")
        self.assertRaises(SyntaxError, get_tokens, "0b1_2")
        self.assertRaises(SyntaxError, get_tokens, "0b2")
        self.assertRaises(SyntaxError, get_tokens, "0b1_")
        self.assertRaises(SyntaxError, get_tokens, "0b")
        self.assertRaises(SyntaxError, get_tokens, "0o18")
        self.assertRaises(SyntaxError, get_tokens, "0o1_8")
        self.assertRaises(SyntaxError, get_tokens, "0o8")
        self.assertRaises(SyntaxError, get_tokens, "0o1_")
        self.assertRaises(SyntaxError, get_tokens, "0o")
        self.assertRaises(SyntaxError, get_tokens, "0x1_")
        self.assertRaises(SyntaxError, get_tokens, "0x")
        self.assertRaises(SyntaxError, get_tokens, "1_")
        self.assertRaises(SyntaxError, get_tokens, "012")
        self.assertRaises(SyntaxError, get_tokens, "1.2_")
        self.assertRaises(SyntaxError, get_tokens, "1e2_")
        self.assertRaises(SyntaxError, get_tokens, "1e+")

        self.assertRaises(SyntaxError, get_tokens, "'sdfsdf")
        self.assertRaises(SyntaxError, get_tokens, "'''sdfsdf''")

        self.assertRaises(SyntaxError, get_tokens, "("*1000+"a"+")"*1000)
        self.assertRaises(SyntaxError, get_tokens, "]")

    def test_max_indent(self):
        MAXINDENT = 100

        def generate_source(indents):
            source = ''.join(('  ' * x) + 'if True:\n' for x in range(indents))
            source += '  ' * indents + 'pass\n'
            return source

        valid = generate_source(MAXINDENT - 1)
        tokens = list(_generate_tokens_from_c_tokenizer(valid))
        self.assertEqual(tokens[-1].type, DEDENT)
        compile(valid, "<string>", "exec")

        invalid = generate_source(MAXINDENT)
        tokens = list(_generate_tokens_from_c_tokenizer(invalid))
        self.assertEqual(tokens[-1].type, NEWLINE)
        self.assertRaises(
            IndentationError, compile, invalid, "<string>", "exec"
        )

    def test_continuation_lines_indentation(self):
        def get_tokens(string):
            return [(kind, string) for (kind, string, *_) in _generate_tokens_from_c_tokenizer(string)]

        code = dedent("""
            def fib(n):
                \\
            '''Print a Fibonacci series up to n.'''
                \\
            a, b = 0, 1
        """)

        self.check_tokenize(code, """\
    NAME       'def'         (2, 0) (2, 3)
    NAME       'fib'         (2, 4) (2, 7)
    LPAR       '('           (2, 7) (2, 8)
    NAME       'n'           (2, 8) (2, 9)
    RPAR       ')'           (2, 9) (2, 10)
    COLON      ':'           (2, 10) (2, 11)
    NEWLINE    ''            (2, 11) (2, 11)
    INDENT     ''            (4, -1) (4, -1)
    STRING     "'''Print a Fibonacci series up to n.'''" (4, 0) (4, 39)
    NEWLINE    ''            (4, 39) (4, 39)
    NAME       'a'           (6, 0) (6, 1)
    COMMA      ','           (6, 1) (6, 2)
    NAME       'b'           (6, 3) (6, 4)
    EQUAL      '='           (6, 5) (6, 6)
    NUMBER     '0'           (6, 7) (6, 8)
    COMMA      ','           (6, 8) (6, 9)
    NUMBER     '1'           (6, 10) (6, 11)
    NEWLINE    ''            (6, 11) (6, 11)
    DEDENT     ''            (6, -1) (6, -1)
        """)

        code_no_cont = dedent("""
            def fib(n):
                '''Print a Fibonacci series up to n.'''
                a, b = 0, 1
        """)

        self.assertEqual(get_tokens(code), get_tokens(code_no_cont))

        code = dedent("""
            pass
                \\

            pass
        """)

        self.check_tokenize(code, """\
    NAME       'pass'        (2, 0) (2, 4)
    NEWLINE    ''            (2, 4) (2, 4)
    NAME       'pass'        (5, 0) (5, 4)
    NEWLINE    ''            (5, 4) (5, 4)
        """)

        code_no_cont = dedent("""
            pass
            pass
        """)

        self.assertEqual(get_tokens(code), get_tokens(code_no_cont))

        code = dedent("""
            if x:
                y = 1
                \\
                        \\
                    \\
                \\
                foo = 1
        """)

        self.check_tokenize(code, """\
    NAME       'if'          (2, 0) (2, 2)
    NAME       'x'           (2, 3) (2, 4)
    COLON      ':'           (2, 4) (2, 5)
    NEWLINE    ''            (2, 5) (2, 5)
    INDENT     ''            (3, -1) (3, -1)
    NAME       'y'           (3, 4) (3, 5)
    EQUAL      '='           (3, 6) (3, 7)
    NUMBER     '1'           (3, 8) (3, 9)
    NEWLINE    ''            (3, 9) (3, 9)
    NAME       'foo'         (8, 4) (8, 7)
    EQUAL      '='           (8, 8) (8, 9)
    NUMBER     '1'           (8, 10) (8, 11)
    NEWLINE    ''            (8, 11) (8, 11)
    DEDENT     ''            (8, -1) (8, -1)
        """)

        code_no_cont = dedent("""
            if x:
                y = 1
                foo = 1
        """)

        self.assertEqual(get_tokens(code), get_tokens(code_no_cont))


class CTokenizerBufferTests(unittest.TestCase):
    def test_newline_at_the_end_of_buffer(self):
        # See issue 99581: Make sure that if we need to add a new line at the
        # end of the buffer, we have enough space in the buffer, specially when
        # the current line is as long as the buffer space available.
        test_script = f"""\
        #coding: latin-1
        #{"a"*10000}
        #{"a"*10002}"""
        with os_helper.temp_dir() as temp_dir:
            file_name = make_script(temp_dir, 'foo', test_script)
            run_test_script(file_name)


if __name__ == "__main__":
    unittest.main()
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2021 Taneli Hukkinen
# Licensed to PSF under a Contributor Agreement.

__all__ = ("tomllib",)

# By changing this one line, we can run the tests against
# a different module name.
import tomllib

import os
from test.support import load_package_tests

def load_tests(*args):
    return load_package_tests(os.path.dirname(__file__), *args)
import unittest

from . import load_tests


unittest.main()
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2021 Taneli Hukkinen
# Licensed to PSF under a Contributor Agreement.

"""Utilities for tests that are in the "burntsushi" format."""

import datetime
from typing import Any

# Aliases for converting TOML compliance format [1] to BurntSushi format [2]
# [1] https://github.com/toml-lang/compliance/blob/db7c3211fda30ff9ddb10292f4aeda7e2e10abc4/docs/json-encoding.md  # noqa: E501
# [2] https://github.com/BurntSushi/toml-test/blob/4634fdf3a6ecd6aaea5f4cdcd98b2733c2694993/README.md  # noqa: E501
_aliases = {
    "boolean": "bool",
    "offset datetime": "datetime",
    "local datetime": "datetime-local",
    "local date": "date-local",
    "local time": "time-local",
}


def convert(obj):  # noqa: C901
    if isinstance(obj, str):
        return {"type": "string", "value": obj}
    elif isinstance(obj, bool):
        return {"type": "bool", "value": str(obj).lower()}
    elif isinstance(obj, int):
        return {"type": "integer", "value": str(obj)}
    elif isinstance(obj, float):
        return {"type": "float", "value": _normalize_float_str(str(obj))}
    elif isinstance(obj, datetime.datetime):
        val = _normalize_datetime_str(obj.isoformat())
        if obj.tzinfo:
            return {"type": "datetime", "value": val}
        return {"type": "datetime-local", "value": val}
    elif isinstance(obj, datetime.time):
        return {
            "type": "time-local",
            "value": _normalize_localtime_str(str(obj)),
        }
    elif isinstance(obj, datetime.date):
        return {
            "type": "date-local",
            "value": str(obj),
        }
    elif isinstance(obj, list):
        return [convert(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert(v) for k, v in obj.items()}
    raise Exception("unsupported type")


def normalize(obj: Any) -> Any:
    """Normalize test objects.

    This normalizes primitive values (e.g. floats), and also converts from
    TOML compliance format [1] to BurntSushi format [2].

    [1] https://github.com/toml-lang/compliance/blob/db7c3211fda30ff9ddb10292f4aeda7e2e10abc4/docs/json-encoding.md  # noqa: E501
    [2] https://github.com/BurntSushi/toml-test/blob/4634fdf3a6ecd6aaea5f4cdcd98b2733c2694993/README.md  # noqa: E501
    """
    if isinstance(obj, list):
        return [normalize(item) for item in obj]
    if isinstance(obj, dict):
        if "type" in obj and "value" in obj:
            type_ = obj["type"]
            norm_type = _aliases.get(type_, type_)
            value = obj["value"]
            if norm_type == "float":
                norm_value = _normalize_float_str(value)
            elif norm_type in {"datetime", "datetime-local"}:
                norm_value = _normalize_datetime_str(value)
            elif norm_type == "time-local":
                norm_value = _normalize_localtime_str(value)
            else:
                norm_value = value

            if norm_type == "array":
                return [normalize(item) for item in value]
            return {"type": norm_type, "value": norm_value}
        return {k: normalize(v) for k, v in obj.items()}
    raise AssertionError("Burntsushi fixtures should be dicts/lists only")


def _normalize_datetime_str(dt_str: str) -> str:
    if dt_str[-1].lower() == "z":
        dt_str = dt_str[:-1] + "+00:00"

    date = dt_str[:10]
    rest = dt_str[11:]

    if "+" in rest:
        sign = "+"
    elif "-" in rest:
        sign = "-"
    else:
        sign = ""

    if sign:
        time, _, offset = rest.partition(sign)
    else:
        time = rest
        offset = ""

    time = time.rstrip("0") if "." in time else time
    return date + "T" + time + sign + offset


def _normalize_localtime_str(lt_str: str) -> str:
    return lt_str.rstrip("0") if "." in lt_str else lt_str


def _normalize_float_str(float_str: str) -> str:
    as_float = float(float_str)

    # Normalize "-0.0" and "+0.0"
    if as_float == 0:
        return "0"

    return str(as_float)
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2021 Taneli Hukkinen
# Licensed to PSF under a Contributor Agreement.

import json
from pathlib import Path
import unittest

from . import burntsushi, tomllib


class MissingFile:
    def __init__(self, path: Path):
        self.path = path


DATA_DIR = Path(__file__).parent / "data"

VALID_FILES = tuple((DATA_DIR / "valid").glob("**/*.toml"))
assert VALID_FILES, "Valid TOML test files not found"

_expected_files = []
for p in VALID_FILES:
    json_path = p.with_suffix(".json")
    try:
        text = json.loads(json_path.read_bytes().decode())
    except FileNotFoundError:
        text = MissingFile(json_path)
    _expected_files.append(text)
VALID_FILES_EXPECTED = tuple(_expected_files)

INVALID_FILES = tuple((DATA_DIR / "invalid").glob("**/*.toml"))
assert INVALID_FILES, "Invalid TOML test files not found"


class TestData(unittest.TestCase):
    def test_invalid(self):
        for invalid in INVALID_FILES:
            with self.subTest(msg=invalid.stem):
                toml_bytes = invalid.read_bytes()
                try:
                    toml_str = toml_bytes.decode()
                except UnicodeDecodeError:
                    # Some BurntSushi tests are not valid UTF-8. Skip those.
                    continue
                with self.assertRaises(tomllib.TOMLDecodeError):
                    tomllib.loads(toml_str)

    def test_valid(self):
        for valid, expected in zip(VALID_FILES, VALID_FILES_EXPECTED):
            with self.subTest(msg=valid.stem):
                if isinstance(expected, MissingFile):
                    # For a poor man's xfail, assert that this is one of the
                    # test cases where expected data is known to be missing.
                    assert valid.stem in {
                        "qa-array-inline-nested-1000",
                        "qa-table-inline-nested-1000",
                    }
                    continue
                toml_str = valid.read_bytes().decode()
                actual = tomllib.loads(toml_str)
                actual = burntsushi.convert(actual)
                expected = burntsushi.normalize(expected)
                self.assertEqual(actual, expected)
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2021 Taneli Hukkinen
# Licensed to PSF under a Contributor Agreement.

import unittest

from . import tomllib


class TestError(unittest.TestCase):
    def test_line_and_col(self):
        with self.assertRaises(tomllib.TOMLDecodeError) as exc_info:
            tomllib.loads("val=.")
        self.assertEqual(str(exc_info.exception), "Invalid value (at line 1, column 5)")

        with self.assertRaises(tomllib.TOMLDecodeError) as exc_info:
            tomllib.loads(".")
        self.assertEqual(
            str(exc_info.exception), "Invalid statement (at line 1, column 1)"
        )

        with self.assertRaises(tomllib.TOMLDecodeError) as exc_info:
            tomllib.loads("\n\nval=.")
        self.assertEqual(str(exc_info.exception), "Invalid value (at line 3, column 5)")

        with self.assertRaises(tomllib.TOMLDecodeError) as exc_info:
            tomllib.loads("\n\n.")
        self.assertEqual(
            str(exc_info.exception), "Invalid statement (at line 3, column 1)"
        )

    def test_missing_value(self):
        with self.assertRaises(tomllib.TOMLDecodeError) as exc_info:
            tomllib.loads("\n\nfwfw=")
        self.assertEqual(str(exc_info.exception), "Invalid value (at end of document)")

    def test_invalid_char_quotes(self):
        with self.assertRaises(tomllib.TOMLDecodeError) as exc_info:
            tomllib.loads("v = '\n'")
        self.assertTrue(" '\\n' " in str(exc_info.exception))

    def test_module_name(self):
        self.assertEqual(tomllib.TOMLDecodeError().__module__, tomllib.__name__)

    def test_invalid_parse_float(self):
        def dict_returner(s: str) -> dict:
            return {}

        def list_returner(s: str) -> list:
            return []

        for invalid_parse_float in (dict_returner, list_returner):
            with self.assertRaises(ValueError) as exc_info:
                tomllib.loads("f=0.1", parse_float=invalid_parse_float)
            self.assertEqual(
                str(exc_info.exception), "parse_float must not return dicts or lists"
            )
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2021 Taneli Hukkinen
# Licensed to PSF under a Contributor Agreement.

import copy
import datetime
from decimal import Decimal as D
from pathlib import Path
import sys
import tempfile
import unittest

from . import tomllib


class TestMiscellaneous(unittest.TestCase):
    def test_load(self):
        content = "one=1 \n two='two' \n arr=[]"
        expected = {"one": 1, "two": "two", "arr": []}
        with tempfile.TemporaryDirectory() as tmp_dir_path:
            file_path = Path(tmp_dir_path) / "test.toml"
            file_path.write_text(content)

            with open(file_path, "rb") as bin_f:
                actual = tomllib.load(bin_f)
        self.assertEqual(actual, expected)

    def test_incorrect_load(self):
        content = "one=1"
        with tempfile.TemporaryDirectory() as tmp_dir_path:
            file_path = Path(tmp_dir_path) / "test.toml"
            file_path.write_text(content)

            with open(file_path, "r") as txt_f:
                with self.assertRaises(TypeError):
                    tomllib.load(txt_f)  # type: ignore[arg-type]

    def test_parse_float(self):
        doc = """
              val=0.1
              biggest1=inf
              biggest2=+inf
              smallest=-inf
              notnum1=nan
              notnum2=-nan
              notnum3=+nan
              """
        obj = tomllib.loads(doc, parse_float=D)
        expected = {
            "val": D("0.1"),
            "biggest1": D("inf"),
            "biggest2": D("inf"),
            "smallest": D("-inf"),
            "notnum1": D("nan"),
            "notnum2": D("-nan"),
            "notnum3": D("nan"),
        }
        for k, expected_val in expected.items():
            actual_val = obj[k]
            self.assertIsInstance(actual_val, D)
            if actual_val.is_nan():
                self.assertTrue(expected_val.is_nan())
            else:
                self.assertEqual(actual_val, expected_val)

    def test_deepcopy(self):
        doc = """
              [bliibaa.diibaa]
              offsettime=[1979-05-27T00:32:00.999999-07:00]
              """
        obj = tomllib.loads(doc)
        obj_copy = copy.deepcopy(obj)
        self.assertEqual(obj_copy, obj)
        expected_obj = {
            "bliibaa": {
                "diibaa": {
                    "offsettime": [
                        datetime.datetime(
                            1979,
                            5,
                            27,
                            0,
                            32,
                            0,
                            999999,
                            tzinfo=datetime.timezone(datetime.timedelta(hours=-7)),
                        )
                    ]
                }
            }
        }
        self.assertEqual(obj_copy, expected_obj)

    def test_inline_array_recursion_limit(self):
        # 465 with default recursion limit
        nest_count = int(sys.getrecursionlimit() * 0.465)
        recursive_array_toml = "arr = " + nest_count * "[" + nest_count * "]"
        tomllib.loads(recursive_array_toml)

    def test_inline_table_recursion_limit(self):
        # 310 with default recursion limit
        nest_count = int(sys.getrecursionlimit() * 0.31)
        recursive_table_toml = nest_count * "key = {" + nest_count * "}"
        tomllib.loads(recursive_table_toml)
"""Support functions for testing scripts in the Tools directory."""
import contextlib
import importlib
import os.path
import unittest
from test import support
from test.support import import_helper


if support.check_sanitizer(address=True, memory=True):
    # bpo-46633: Skip the test because it is too slow when Python is built
    # with ASAN/MSAN: between 5 and 20 minutes on GitHub Actions.
    raise unittest.SkipTest("test too slow on ASAN/MSAN build")


if not support.has_subprocess_support:
    raise unittest.SkipTest("test module requires subprocess")


basepath = os.path.normpath(
        os.path.dirname(                 # <src/install dir>
            os.path.dirname(                # Lib
                os.path.dirname(                # test
                    os.path.dirname(__file__)))))    # test_tools

toolsdir = os.path.join(basepath, 'Tools')
scriptsdir = os.path.join(toolsdir, 'scripts')

def skip_if_missing(tool=None):
    if tool:
        tooldir = os.path.join(toolsdir, tool)
    else:
        tool = 'scripts'
        tooldir = scriptsdir
    if not os.path.isdir(tooldir):
        raise unittest.SkipTest(f'{tool} directory could not be found')

@contextlib.contextmanager
def imports_under_tool(name, *subdirs):
    tooldir = os.path.join(toolsdir, name, *subdirs)
    with import_helper.DirsOnSysPath(tooldir) as cm:
        yield cm

def import_tool(toolname):
    with import_helper.DirsOnSysPath(scriptsdir):
        return importlib.import_module(toolname)

def load_tests(*args):
    return support.load_package_tests(os.path.dirname(__file__), *args)
from test.test_tools import load_tests
import unittest

unittest.main()
"""Sanity-check tests for the "freeze" tool."""

import sys
import textwrap
import unittest

from test import support
from test.support import os_helper
from test.test_tools import imports_under_tool, skip_if_missing

skip_if_missing('freeze')
with imports_under_tool('freeze', 'test'):
    import freeze as helper

@support.requires_zlib()
@unittest.skipIf(sys.platform.startswith('win'), 'not supported on Windows')
@support.skip_if_buildbot('not all buildbots have enough space')
class TestFreeze(unittest.TestCase):

    def test_freeze_simple_script(self):
        script = textwrap.dedent("""
            import sys
            print('running...')
            sys.exit(0)
            """)
        with os_helper.temp_dir() as outdir:
            outdir, scriptfile, python = helper.prepare(script, outdir)
            executable = helper.freeze(python, scriptfile, outdir)
            text = helper.run(executable)
        self.assertEqual(text, 'running...')
"""Tests to cover the Tools/i18n package"""

import os
import sys
import unittest
from textwrap import dedent

from test.support.script_helper import assert_python_ok
from test.test_tools import skip_if_missing, toolsdir
from test.support.os_helper import temp_cwd, temp_dir


skip_if_missing()


class Test_pygettext(unittest.TestCase):
    """Tests for the pygettext.py tool"""

    script = os.path.join(toolsdir,'i18n', 'pygettext.py')

    def get_header(self, data):
        """ utility: return the header of a .po file as a dictionary """
        headers = {}
        for line in data.split('\n'):
            if not line or line.startswith(('#', 'msgid','msgstr')):
                continue
            line = line.strip('"')
            key, val = line.split(':',1)
            headers[key] = val.strip()
        return headers

    def get_msgids(self, data):
        """ utility: return all msgids in .po file as a list of strings """
        msgids = []
        reading_msgid = False
        cur_msgid = []
        for line in data.split('\n'):
            if reading_msgid:
                if line.startswith('"'):
                    cur_msgid.append(line.strip('"'))
                else:
                    msgids.append('\n'.join(cur_msgid))
                    cur_msgid = []
                    reading_msgid = False
                    continue
            if line.startswith('msgid '):
                line = line[len('msgid '):]
                cur_msgid.append(line.strip('"'))
                reading_msgid = True
        else:
            if reading_msgid:
                msgids.append('\n'.join(cur_msgid))

        return msgids

    def extract_docstrings_from_str(self, module_content):
        """ utility: return all msgids extracted from module_content """
        filename = 'test_docstrings.py'
        with temp_cwd(None) as cwd:
            with open(filename, 'w', encoding='utf-8') as fp:
                fp.write(module_content)
            assert_python_ok(self.script, '-D', filename)
            with open('messages.pot', encoding='utf-8') as fp:
                data = fp.read()
        return self.get_msgids(data)

    def test_header(self):
        """Make sure the required fields are in the header, according to:
           http://www.gnu.org/software/gettext/manual/gettext.html#Header-Entry
        """
        with temp_cwd(None) as cwd:
            assert_python_ok(self.script)
            with open('messages.pot', encoding='utf-8') as fp:
                data = fp.read()
            header = self.get_header(data)

            self.assertIn("Project-Id-Version", header)
            self.assertIn("POT-Creation-Date", header)
            self.assertIn("PO-Revision-Date", header)
            self.assertIn("Last-Translator", header)
            self.assertIn("Language-Team", header)
            self.assertIn("MIME-Version", header)
            self.assertIn("Content-Type", header)
            self.assertIn("Content-Transfer-Encoding", header)
            self.assertIn("Generated-By", header)

            # not clear if these should be required in POT (template) files
            #self.assertIn("Report-Msgid-Bugs-To", header)
            #self.assertIn("Language", header)

            #"Plural-Forms" is optional

    @unittest.skipIf(sys.platform.startswith('aix'),
                     'bpo-29972: broken test on AIX')
    def test_POT_Creation_Date(self):
        """ Match the date format from xgettext for POT-Creation-Date """
        from datetime import datetime
        with temp_cwd(None) as cwd:
            assert_python_ok(self.script)
            with open('messages.pot', encoding='utf-8') as fp:
                data = fp.read()
            header = self.get_header(data)
            creationDate = header['POT-Creation-Date']

            # peel off the escaped newline at the end of string
            if creationDate.endswith('\\n'):
                creationDate = creationDate[:-len('\\n')]

            # This will raise if the date format does not exactly match.
            datetime.strptime(creationDate, '%Y-%m-%d %H:%M%z')

    def test_funcdocstring(self):
        for doc in ('"""doc"""', "r'''doc'''", "R'doc'", 'u"doc"'):
            with self.subTest(doc):
                msgids = self.extract_docstrings_from_str(dedent('''\
                def foo(bar):
                    %s
                ''' % doc))
                self.assertIn('doc', msgids)

    def test_funcdocstring_bytes(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        def foo(bar):
            b"""doc"""
        '''))
        self.assertFalse([msgid for msgid in msgids if 'doc' in msgid])

    def test_funcdocstring_fstring(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        def foo(bar):
            f"""doc"""
        '''))
        self.assertFalse([msgid for msgid in msgids if 'doc' in msgid])

    def test_classdocstring(self):
        for doc in ('"""doc"""', "r'''doc'''", "R'doc'", 'u"doc"'):
            with self.subTest(doc):
                msgids = self.extract_docstrings_from_str(dedent('''\
                class C:
                    %s
                ''' % doc))
                self.assertIn('doc', msgids)

    def test_classdocstring_bytes(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        class C:
            b"""doc"""
        '''))
        self.assertFalse([msgid for msgid in msgids if 'doc' in msgid])

    def test_classdocstring_fstring(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        class C:
            f"""doc"""
        '''))
        self.assertFalse([msgid for msgid in msgids if 'doc' in msgid])

    def test_moduledocstring(self):
        for doc in ('"""doc"""', "r'''doc'''", "R'doc'", 'u"doc"'):
            with self.subTest(doc):
                msgids = self.extract_docstrings_from_str(dedent('''\
                %s
                ''' % doc))
                self.assertIn('doc', msgids)

    def test_moduledocstring_bytes(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        b"""doc"""
        '''))
        self.assertFalse([msgid for msgid in msgids if 'doc' in msgid])

    def test_moduledocstring_fstring(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        f"""doc"""
        '''))
        self.assertFalse([msgid for msgid in msgids if 'doc' in msgid])

    def test_msgid(self):
        msgids = self.extract_docstrings_from_str(
                '''_("""doc""" r'str' u"ing")''')
        self.assertIn('docstring', msgids)

    def test_msgid_bytes(self):
        msgids = self.extract_docstrings_from_str('_(b"""doc""")')
        self.assertFalse([msgid for msgid in msgids if 'doc' in msgid])

    def test_msgid_fstring(self):
        msgids = self.extract_docstrings_from_str('_(f"""doc""")')
        self.assertFalse([msgid for msgid in msgids if 'doc' in msgid])

    def test_funcdocstring_annotated_args(self):
        """ Test docstrings for functions with annotated args """
        msgids = self.extract_docstrings_from_str(dedent('''\
        def foo(bar: str):
            """doc"""
        '''))
        self.assertIn('doc', msgids)

    def test_funcdocstring_annotated_return(self):
        """ Test docstrings for functions with annotated return type """
        msgids = self.extract_docstrings_from_str(dedent('''\
        def foo(bar) -> str:
            """doc"""
        '''))
        self.assertIn('doc', msgids)

    def test_funcdocstring_defvalue_args(self):
        """ Test docstring for functions with default arg values """
        msgids = self.extract_docstrings_from_str(dedent('''\
        def foo(bar=()):
            """doc"""
        '''))
        self.assertIn('doc', msgids)

    def test_funcdocstring_multiple_funcs(self):
        """ Test docstring extraction for multiple functions combining
        annotated args, annotated return types and default arg values
        """
        msgids = self.extract_docstrings_from_str(dedent('''\
        def foo1(bar: tuple=()) -> str:
            """doc1"""

        def foo2(bar: List[1:2]) -> (lambda x: x):
            """doc2"""

        def foo3(bar: 'func'=lambda x: x) -> {1: 2}:
            """doc3"""
        '''))
        self.assertIn('doc1', msgids)
        self.assertIn('doc2', msgids)
        self.assertIn('doc3', msgids)

    def test_classdocstring_early_colon(self):
        """ Test docstring extraction for a class with colons occurring within
        the parentheses.
        """
        msgids = self.extract_docstrings_from_str(dedent('''\
        class D(L[1:2], F({1: 2}), metaclass=M(lambda x: x)):
            """doc"""
        '''))
        self.assertIn('doc', msgids)

    def test_calls_in_fstrings(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        f"{_('foo bar')}"
        '''))
        self.assertIn('foo bar', msgids)

    def test_calls_in_fstrings_raw(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        rf"{_('foo bar')}"
        '''))
        self.assertIn('foo bar', msgids)

    def test_calls_in_fstrings_nested(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        f"""{f'{_("foo bar")}'}"""
        '''))
        self.assertIn('foo bar', msgids)

    def test_calls_in_fstrings_attribute(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        f"{obj._('foo bar')}"
        '''))
        self.assertIn('foo bar', msgids)

    def test_calls_in_fstrings_with_call_on_call(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        f"{type(str)('foo bar')}"
        '''))
        self.assertNotIn('foo bar', msgids)

    def test_calls_in_fstrings_with_format(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        f"{_('foo {bar}').format(bar='baz')}"
        '''))
        self.assertIn('foo {bar}', msgids)

    def test_calls_in_fstrings_with_wrong_input_1(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        f"{_(f'foo {bar}')}"
        '''))
        self.assertFalse([msgid for msgid in msgids if 'foo {bar}' in msgid])

    def test_calls_in_fstrings_with_wrong_input_2(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        f"{_(1)}"
        '''))
        self.assertNotIn(1, msgids)

    def test_calls_in_fstring_with_multiple_args(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        f"{_('foo', 'bar')}"
        '''))
        self.assertNotIn('foo', msgids)
        self.assertNotIn('bar', msgids)

    def test_calls_in_fstring_with_keyword_args(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        f"{_('foo', bar='baz')}"
        '''))
        self.assertNotIn('foo', msgids)
        self.assertNotIn('bar', msgids)
        self.assertNotIn('baz', msgids)

    def test_calls_in_fstring_with_partially_wrong_expression(self):
        msgids = self.extract_docstrings_from_str(dedent('''\
        f"{_(f'foo') + _('bar')}"
        '''))
        self.assertNotIn('foo', msgids)
        self.assertIn('bar', msgids)

    def test_files_list(self):
        """Make sure the directories are inspected for source files
           bpo-31920
        """
        text1 = 'Text to translate1'
        text2 = 'Text to translate2'
        text3 = 'Text to ignore'
        with temp_cwd(None), temp_dir(None) as sdir:
            os.mkdir(os.path.join(sdir, 'pypkg'))
            with open(os.path.join(sdir, 'pypkg', 'pymod.py'), 'w',
                      encoding='utf-8') as sfile:
                sfile.write(f'_({text1!r})')
            os.mkdir(os.path.join(sdir, 'pkg.py'))
            with open(os.path.join(sdir, 'pkg.py', 'pymod2.py'), 'w',
                      encoding='utf-8') as sfile:
                sfile.write(f'_({text2!r})')
            os.mkdir(os.path.join(sdir, 'CVS'))
            with open(os.path.join(sdir, 'CVS', 'pymod3.py'), 'w',
                      encoding='utf-8') as sfile:
                sfile.write(f'_({text3!r})')
            assert_python_ok(self.script, sdir)
            with open('messages.pot', encoding='utf-8') as fp:
                data = fp.read()
            self.assertIn(f'msgid "{text1}"', data)
            self.assertIn(f'msgid "{text2}"', data)
            self.assertNotIn(text3, data)
"""Tests for scripts in the Tools directory.

This file contains regression tests for some of the scripts found in the
Tools directory of a Python checkout or tarball, such as reindent.py.
"""

import os
import unittest
from test.support.script_helper import assert_python_ok
from test.support import findfile

from test.test_tools import toolsdir, skip_if_missing

skip_if_missing()

class ReindentTests(unittest.TestCase):
    script = os.path.join(toolsdir, 'patchcheck', 'reindent.py')

    def test_noargs(self):
        assert_python_ok(self.script)

    def test_help(self):
        rc, out, err = assert_python_ok(self.script, '-h')
        self.assertEqual(out, b'')
        self.assertGreater(err, b'')

    def test_reindent_file_with_bad_encoding(self):
        bad_coding_path = findfile('bad_coding.py')
        rc, out, err = assert_python_ok(self.script, '-r', bad_coding_path)
        self.assertEqual(out, b'')
        self.assertNotEqual(err, b'')


if __name__ == '__main__':
    unittest.main()
"""Tests for scripts in the Tools directory.

This file contains extremely basic regression tests for the scripts found in
the Tools directory of a Python checkout or tarball which don't have separate
tests of their own.
"""

import os
import sys
import unittest
from test.support import import_helper

from test.test_tools import scriptsdir, import_tool, skip_if_missing

skip_if_missing()

class TestSundryScripts(unittest.TestCase):
    # At least make sure the rest don't have syntax errors.  When tests are
    # added for a script it should be added to the allowlist below.

    # scripts that have independent tests.
    allowlist = ['reindent']
    # scripts that can't be imported without running
    denylist = ['make_ctype']
    # denylisted for other reasons
    other = ['2to3']

    skiplist = denylist + allowlist + other

    # import logging registers "atfork" functions which keep indirectly the
    # logging module dictionary alive. Mock the function to be able to unload
    # cleanly the logging module.
    @import_helper.mock_register_at_fork
    def test_sundry(self, mock_os):
        old_modules = import_helper.modules_setup()
        try:
            for fn in os.listdir(scriptsdir):
                if not fn.endswith('.py'):
                    continue

                name = fn[:-3]
                if name in self.skiplist:
                    continue

                import_tool(name)
        finally:
            # Unload all modules loaded in this test
            import_helper.modules_cleanup(*old_modules)


if __name__ == '__main__':
    unittest.main()
import os
from pickle import dump
import sys
from test.support import captured_stdout
from test.support.os_helper import (TESTFN, rmtree, unlink)
from test.support.script_helper import assert_python_ok, assert_python_failure
import textwrap
import unittest

import trace
from trace import Trace

from test.tracedmodules import testmod

##
## See also test_sys_settrace.py, which contains tests that cover
## tracing of many more code blocks.
##

#------------------------------- Utilities -----------------------------------#

def fix_ext_py(filename):
    """Given a .pyc filename converts it to the appropriate .py"""
    if filename.endswith('.pyc'):
        filename = filename[:-1]
    return filename

def my_file_and_modname():
    """The .py file and module name of this file (__file__)"""
    modname = os.path.splitext(os.path.basename(__file__))[0]
    return fix_ext_py(__file__), modname

def get_firstlineno(func):
    return func.__code__.co_firstlineno

#-------------------- Target functions for tracing ---------------------------#
#
# The relative line numbers of lines in these functions matter for verifying
# tracing. Please modify the appropriate tests if you change one of the
# functions. Absolute line numbers don't matter.
#

def traced_func_linear(x, y):
    a = x
    b = y
    c = a + b
    return c

def traced_func_loop(x, y):
    c = x
    for i in range(5):
        c += y
    return c

def traced_func_importing(x, y):
    return x + y + testmod.func(1)

def traced_func_simple_caller(x):
    c = traced_func_linear(x, x)
    return c + x

def traced_func_importing_caller(x):
    k = traced_func_simple_caller(x)
    k += traced_func_importing(k, x)
    return k

def traced_func_generator(num):
    c = 5       # executed once
    for i in range(num):
        yield i + c

def traced_func_calling_generator():
    k = 0
    for i in traced_func_generator(10):
        k += i

def traced_doubler(num):
    return num * 2

def traced_capturer(*args, **kwargs):
    return args, kwargs

def traced_caller_list_comprehension():
    k = 10
    mylist = [traced_doubler(i) for i in range(k)]
    return mylist

def traced_decorated_function():
    def decorator1(f):
        return f
    def decorator_fabric():
        def decorator2(f):
            return f
        return decorator2
    @decorator1
    @decorator_fabric()
    def func():
        pass
    func()


class TracedClass(object):
    def __init__(self, x):
        self.a = x

    def inst_method_linear(self, y):
        return self.a + y

    def inst_method_calling(self, x):
        c = self.inst_method_linear(x)
        return c + traced_func_linear(x, c)

    @classmethod
    def class_method_linear(cls, y):
        return y * 2

    @staticmethod
    def static_method_linear(y):
        return y * 2


#------------------------------ Test cases -----------------------------------#


class TestLineCounts(unittest.TestCase):
    """White-box testing of line-counting, via runfunc"""
    def setUp(self):
        self.addCleanup(sys.settrace, sys.gettrace())
        self.tracer = Trace(count=1, trace=0, countfuncs=0, countcallers=0)
        self.my_py_filename = fix_ext_py(__file__)

    def test_traced_func_linear(self):
        result = self.tracer.runfunc(traced_func_linear, 2, 5)
        self.assertEqual(result, 7)

        # all lines are executed once
        expected = {}
        firstlineno = get_firstlineno(traced_func_linear)
        for i in range(1, 5):
            expected[(self.my_py_filename, firstlineno +  i)] = 1

        self.assertEqual(self.tracer.results().counts, expected)

    def test_traced_func_loop(self):
        self.tracer.runfunc(traced_func_loop, 2, 3)

        firstlineno = get_firstlineno(traced_func_loop)
        expected = {
            (self.my_py_filename, firstlineno + 1): 1,
            (self.my_py_filename, firstlineno + 2): 6,
            (self.my_py_filename, firstlineno + 3): 5,
            (self.my_py_filename, firstlineno + 4): 1,
