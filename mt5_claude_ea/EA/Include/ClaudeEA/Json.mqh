//+------------------------------------------------------------------+
//| Json.mqh - strict parser for ONE FLAT JSON object.                |
//| Values: string | number | true | false | null. Anything else      |
//| (nesting, arrays, duplicate keys, trailing text, oversize input)  |
//| fails the parse, and the caller treats that as HOLD.              |
//+------------------------------------------------------------------+
#ifndef CLAUDEEA_JSON_MQH
#define CLAUDEEA_JSON_MQH

#define CJ_MAX_LEN   4096
#define CJ_MAX_KEYS  32
#define CJ_T_STRING  0
#define CJ_T_NUMBER  1
#define CJ_T_BOOL    2
#define CJ_T_NULL    3

class CFlatJson
  {
private:
   string            m_src;
   int               m_len;
   int               m_pos;
   string            m_keys[];
   string            m_vals[];
   int               m_types[];
   int               m_count;

   ushort            Peek() { return (m_pos < m_len) ? StringGetCharacter(m_src, m_pos) : 0; }
   void              SkipWs()
     {
      while(m_pos < m_len)
        {
         ushort c = StringGetCharacter(m_src, m_pos);
         if(c == ' ' || c == '\t' || c == '\n' || c == '\r')
            m_pos++;
         else
            break;
        }
     }
   static bool       IsDigit(const ushort c) { return (c >= '0' && c <= '9'); }
   static int        HexVal(const ushort c)
     {
      if(c >= '0' && c <= '9') return (int)(c - '0');
      if(c >= 'a' && c <= 'f') return (int)(c - 'a') + 10;
      if(c >= 'A' && c <= 'F') return (int)(c - 'A') + 10;
      return -1;
     }
   bool              ParseString(string &out);
   bool              ParseNumber(string &out);
   bool              ParseLiteral(const string word);
   int               Find(const string key) const;

public:
                     CFlatJson() { m_len = 0; m_pos = 0; m_count = 0; }
   bool              Parse(const string text);
   int               Count() const { return m_count; }
   bool              Has(const string key) const { return Find(key) >= 0; }
   bool              GetString(const string key, string &out) const;
   bool              GetNumber(const string key, double &out) const;
  };

//+------------------------------------------------------------------+
bool CFlatJson::ParseString(string &out)
  {
   out = "";
   if(Peek() != '"')
      return false;
   m_pos++;
   while(m_pos < m_len)
     {
      ushort c = StringGetCharacter(m_src, m_pos);
      m_pos++;
      if(c == '"')
         return true;
      if(c < 0x20)
         return false;                       // raw control characters are illegal in JSON strings
      if(c != '\\')
        {
         out += ShortToString(c);
         continue;
        }
      if(m_pos >= m_len)
         return false;
      ushort e = StringGetCharacter(m_src, m_pos);
      m_pos++;
      switch(e)
        {
         case '"':  out += "\""; break;
         case '\\': out += "\\"; break;
         case '/':  out += "/";  break;
         case 'b':  out += " ";  break;
         case 'f':  out += " ";  break;
         case 'n':  out += " ";  break;
         case 'r':  out += " ";  break;
         case 't':  out += " ";  break;
         case 'u':
           {
            if(m_pos + 4 > m_len)
               return false;
            int code = 0;
            for(int i = 0; i < 4; i++)
              {
               int h = HexVal(StringGetCharacter(m_src, m_pos + i));
               if(h < 0)
                  return false;
               code = code * 16 + h;
              }
            m_pos += 4;
            out += (code < 0x20) ? " " : ShortToString((ushort)code);
            break;
           }
         default:
            return false;
        }
     }
   return false;                             // unterminated
  }
//+------------------------------------------------------------------+
//| JSON grammar: -?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?      |
//+------------------------------------------------------------------+
bool CFlatJson::ParseNumber(string &out)
  {
   int start = m_pos;
   if(Peek() == '-')
      m_pos++;
   if(!IsDigit(Peek()))
      return false;
   if(Peek() == '0')
      m_pos++;
   else
      while(IsDigit(Peek()))
         m_pos++;
   if(Peek() == '.')
     {
      m_pos++;
      if(!IsDigit(Peek()))
         return false;
      while(IsDigit(Peek()))
         m_pos++;
     }
   if(Peek() == 'e' || Peek() == 'E')
     {
      m_pos++;
      if(Peek() == '+' || Peek() == '-')
         m_pos++;
      if(!IsDigit(Peek()))
         return false;
      while(IsDigit(Peek()))
         m_pos++;
     }
   if(m_pos - start > 32)
      return false;
   out = StringSubstr(m_src, start, m_pos - start);
   return true;
  }
//+------------------------------------------------------------------+
bool CFlatJson::ParseLiteral(const string word)
  {
   int n = StringLen(word);
   if(m_pos + n > m_len || StringSubstr(m_src, m_pos, n) != word)
      return false;
   m_pos += n;
   return true;
  }
//+------------------------------------------------------------------+
int CFlatJson::Find(const string key) const
  {
   for(int i = 0; i < m_count; i++)
      if(m_keys[i] == key)
         return i;
   return -1;
  }
//+------------------------------------------------------------------+
bool CFlatJson::Parse(const string text)
  {
   m_src = text;
   m_len = StringLen(text);
   m_pos = 0;
   m_count = 0;
   ArrayResize(m_keys, 0);
   ArrayResize(m_vals, 0);
   ArrayResize(m_types, 0);
   if(m_len < 2 || m_len > CJ_MAX_LEN)
      return false;
   SkipWs();
   if(Peek() != '{')
      return false;
   m_pos++;
   SkipWs();
   if(Peek() == '}')
      m_pos++;
   else
     {
      while(true)
        {
         SkipWs();
         string key;
         if(!ParseString(key) || key == "" || Find(key) >= 0 || m_count >= CJ_MAX_KEYS)
           { m_count = 0; return false; }
         SkipWs();
         if(Peek() != ':')
           { m_count = 0; return false; }
         m_pos++;
         SkipWs();
         string val = "";
         int    type = -1;
         ushort c = Peek();
         if(c == '"')
           { if(ParseString(val)) type = CJ_T_STRING; }
         else if(c == '-' || IsDigit(c))
           { if(ParseNumber(val)) type = CJ_T_NUMBER; }
         else if(c == 't')
           { if(ParseLiteral("true"))  { val = "true";  type = CJ_T_BOOL; } }
         else if(c == 'f')
           { if(ParseLiteral("false")) { val = "false"; type = CJ_T_BOOL; } }
         else if(c == 'n')
           { if(ParseLiteral("null"))  { val = "";      type = CJ_T_NULL; } }
         if(type < 0)                         // includes '{' and '[' : nesting is not accepted
           { m_count = 0; return false; }
         ArrayResize(m_keys, m_count + 1);
         ArrayResize(m_vals, m_count + 1);
         ArrayResize(m_types, m_count + 1);
         m_keys[m_count] = key;
         m_vals[m_count] = val;
         m_types[m_count] = type;
         m_count++;
         SkipWs();
         if(Peek() == ',')
           { m_pos++; continue; }
         if(Peek() == '}')
           { m_pos++; break; }
         m_count = 0;
         return false;
        }
     }
   SkipWs();
   if(m_pos != m_len)                         // trailing garbage
     { m_count = 0; return false; }
   return true;
  }
//+------------------------------------------------------------------+
bool CFlatJson::GetString(const string key, string &out) const
  {
   int i = Find(key);
   if(i < 0 || m_types[i] != CJ_T_STRING)
      return false;
   out = m_vals[i];
   return true;
  }
//+------------------------------------------------------------------+
bool CFlatJson::GetNumber(const string key, double &out) const
  {
   int i = Find(key);
   if(i < 0 || m_types[i] != CJ_T_NUMBER)
      return false;
   double v = StringToDouble(m_vals[i]);
   if(!MathIsValidNumber(v))
      return false;
   out = v;
   return true;
  }

#endif // CLAUDEEA_JSON_MQH
